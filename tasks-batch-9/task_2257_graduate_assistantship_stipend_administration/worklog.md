# Worklog — task_2257_graduate_assistantship_stipend_administration

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2257_graduate_assistantship_stipend_administration/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T12:39:45.000Z

Task complete. All three scaffold artifacts for task 2257 are written and the package lints clean.

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2257_graduate_assistantship_stipend_administration/`):
- `SCAFFOLD.yaml` — 2,671 lines, §1.0–§1.7 only (no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,102 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5,013 lines, single key `scaffold_corner_design`

**Scaffold contents (§1.0–§1.7)**
- 11 entities (flat topology, all `common_fields: true`): AcademicTerm, Department, StipendPolicy, PayPeriod, GraduateStudent, FundingSource, Appointment, FundingAllocation, StipendDisbursement, RenewalDecision, TaxAssessment
- 8 state machines across 7 entities, including Appointment's two parallel axes (`lifecycle_status`, `payroll_status`); 2 OCC concurrency rules (`expected_appointment_version` on funding-plan replace, `expected_student_version` on assessment create)
- 9 calculations, 2 of them dual-variant: `stipend_pay_schedule` (CALENDAR_DAY / WORKDAY) and `tuition_benefit_tax_assessment` (TERM_PROVISIONAL / CALENDAR_YEAR_FINAL); plus effort banding, remission entitlement, cost-share waterfall, insurance subsidy tiers, effort aggregation with international hour caps, source balance conservation, renewal deadline
- 40 priority-ordered validations, 53 endpoints, 56 error codes, 5 roles (segregation-of-duties model: certifier ≠ notice issuer, cap-overrider ≠ appointment approver), immediate consistency, `difficulty_level: expert_plus`

**Probe instances**
- §1.8: 9 rule_ids × 2 = 18 instances (dual-variant divergence, chained truncation/remainder, parallel-axis + cyclic state, six-level cascade, priority-pair conflicts, threshold exactness, state-dependent gating, boundary window arithmetic, conservation invariants)
- §1.9: 86 instances across all 9 taxonomy sections — 68 with full `test_recipe`, 18 `excluded_because` stubs deferring to named §1.8 instances (entities 11, state_machines 17, calculations 13, validations 20, endpoints 5, errors 7, rbac 6, cross-cutting layers 6, consistency 1)

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint` (1,148 setup/trigger calls scanned; every call resolves to a §1.5 endpoint with a permitted role, payload ⊆ declared inputs, captures resolving to declared `output:` fields, OCC versions always `${var}`, all FKs reverse-reachable)
- All 56 error codes are triggerable across the §1.8 + §1.9 union; instance names unique across both files (0 collisions); no stub carries a `test_recipe`; every cited `difficulty_instance` resolves by name
- All fixtures are empty-DB reproducible and use `POST /_clock/set_current_utc` (startup default `2026-08-01T00:00:00Z`) instead of wall-clock waits

## Step 3: Copy shared files — 2026-09-01T12:39:45.000Z

Copied `INSTRUCTION.md` → `tasks/task_2257_graduate_assistantship_stipend_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T12:53:35.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2257_graduate_assistantship_stipend_administration/workspace/PRD.md`.

**Size:** 456 lines. Ends at §5's last error row — no audit footer in the file.

**Sections**
- §1 Introduction — 3 paragraphs; frames the three-way reconciliation problem and names the two load-bearing commitments (dual state axes, funding conservation).
- §2 Global Specifications & System-Wide Principles — 10 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (pasted byte-verbatim from `section-2.2-response-structure.md`, verified by exact substring match); 2.3 Pagination; 2.4 Term Gating and the Calendar Cascade; 2.5 Record Identity, Audit Fields and Term Sub-Resource Reads; 2.6 Cents, Rounding and the Two Rounding Disciplines; 2.7 Funding Conservation and the Encumbrance Ledger; 2.8 Stale-Read Protection on Funding Plans and Tax Assessments; 2.9 Workload Caps, Effort Aggregation and Segregation of Duties; 2.10 Validation Ordering and the Logical Clock (all 40 priorities as an ordered narrative).
- §3 Business Logic & Workflows — 9 subsections (term frame → departments/students → funding sources → drafting + funding plan → the submission battery → verification/approval/activation → payroll axis → termination/renewal cascades → taxation + term close).
- §4 Endpoint Definitions — intro paragraph plus a 4-column table (Method, Path, Description, Authorized Role(s)) with all 53 endpoints.
- §5 Error Code Catalogue — 2-column table with all 56 error IDs.

**Coverage audit (run mechanically against `SCAFFOLD.yaml`)**

```
Field coverage check:
- entities[].fields: 136 required, 136 present, 0 missing
- endpoints[].request_body: 99 required, 99 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 93 checked, 93 expressed, 0 missing
- entities[].fields[] structured content: 136 checked, 136 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (COMMITTED→RELEASED vs →EXPENDED; DRAFT→SUBMITTED vs RETURNED→SUBMITTED; PAY_SUSPENDED→SCHEDULED vs →PARTIALLY_DISBURSED; RENEW vs NON_RENEW issuance; TERM_PROVISIONAL vs CALENDAR_YEAR_FINAL; CALENDAR_DAY vs WORKDAY proration), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 883
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional verified invariants:** all 56 error IDs appear in §5 exactly once with the scaffold's HTTP status; all 53 endpoints appear as a matching method+path row and the Authorized Role(s) cell is set-equal to `endpoints[].roles` for every row (0 mismatches); zero pseudocode operators (`==`, `>=`, `IN {`, `min(`, `round_half_up`, `truncate_to_cents`, `sum(`) and zero fuzzy-quantity words survive anywhere in the document.

**Two corrections applied during the audit:** the funding-sufficiency rule was restated using `available_amount_cents` directly to match the scaffold's phrasing rather than an algebraically equivalent expansion, and a phantom field name (`department_code`) introduced by a garbled clause in §3.3 was removed.

**Constraint compliance:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read. The one worked example that appears in the PRD (the 400000 + 400000 two-term taxation divergence to 275000) is quoted from `SCAFFOLD.yaml`'s own `variants` block, not from a withheld index.

## Step 5: Generate unit tests — 2026-09-01T14:12:35.000Z

Test generation is complete. Both stages are on disk and all audits pass.

## Files created

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2257_graduate_assistantship_stipend_administration/test_helpers/`** (9 files, ~1,900 lines): `__init__.py` (barrel, 193 exports), `api_client.py` (54 typed endpoint methods), `api_errors.py` (56 error ids), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (world builders `build_term_frame`, `build_funded_appointment`, `build_renewal_review`, `build_assessment`, plus `drive_appointment`), `test_users.py`, `types.py`.

**Stage 2 — `.../test_suite/`**: `conftest.py` plus 18 numbered test modules, ~6,000 lines.

## Test counts

| Queue | Modules | Tests | Instances covered |
|---|---|---|---|
| A (Difficulty, §1.8) | `test_01`–`test_09` | **43** | 18 / 18, every one ≥ 2 tests |
| B (Corner, §1.9) | `test_10`–`test_18` | **68** | 68 / 68 non-stub, 1 test each |
| **Total** | 18 | **111** | 86 design instances |

Queue B by section: entities 11, state_machines 14, calculations 8, validations 18, endpoints 5, errors 1, rbac 6, cross-cutting complexity layers 4, consistency model 1.

## Instances skipped

**None** for cause. Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. The **18 corner entries carrying `excluded_because:`** were not translated, as specified (verified: zero `Design:` tags resolve to a stub name).

Two derivability adjustments were made inside otherwise-faithful translations rather than skipping: `duplicate_natural_keys_rejected` asserts the pay-period list's `total_count == 1` instead of the design's `pay_period_count == 1` (equivalent, and reachable through a declared read), and `tuition_tax_exempt_cap_boundary_at_exact_cap_is_fully_exempt` omits the design's `remaining_cap_cents == 0` because that is an intermediate in the PRD's prose, not a declared entity field.

## Audits

- `python -m pyflakes test_suite/*.py` → rc=0. (`test_helpers/__init__.py` reports only F401 re-export notices, inherent to a barrel module.)
- Design-tag pass: 111/111 tests carry exactly one `Design:` line, it is the last line of every docstring, and all 111 resolve verbatim to a real `name:` in the source yaml. No untagged, dual-tagged, stub-tagged or unknown tags.
- PRD-citation pass: all **212** quoted citations across the suite are verbatim substrings of `workspace/PRD.md` (whitespace-normalised); 0 missing.
- No `pytest.skip`, `xfail`, mocking, `monkeypatch`, or any mention of the scaffold or its section numbers anywhere in the generated code.
- Nothing under `workspace/implementation/` was read or written, and no sibling `task_*/` directory was accessed.

## Step 6: Generate implementation — 2026-09-01T14:12:35.000Z

Verification is complete. Final state of the implementation:

## Files created — 23 under `workspace/implementation/`

| Layer | Files |
|---|---|
| Boot | `start.sh` (guarded `pip install`, then `exec python3 app.py`; cold boot measured at **0.57 s**), `requirements.txt`, `app.py` (app factory + `ApiError`/`HTTPException`/`Exception` handlers) |
| Core | `db.py` (11 empty dicts, logical clock, `insert`/`update`/`force_update`/`touch`, `_seq`/`_mut` counters), `errors.py` (all 56 error_id → HTTP mappings), `response.py` (meta/envelope builders), `middleware.py` (auth + ownership), `validate.py` (shape validation, pagination), `serialize.py` (explicit per-entity field tuples, `Decimal`→`float`), `calc.py` (all named calculations + rounding disciplines) |
| Services | `services/queries.py` (lookup + `*_or_404`), `services/effects.py` (cascades, recomputes, balance/YTD/effort aggregation) |
| Routes | `routes/{terms,students,funding,appointments,allocations,disbursements,renewals,tax,clock}.py` |

~3,000 lines of Python. Storage is in-memory only; every collection starts empty, nothing is seeded.

## Endpoints — 53/53

Dumped Flask's `url_map` and diffed it against SCAFFOLD §1.5: exact match on all 53 paths and methods (terms 11, students 4, funding sources 6, appointments 13, allocations 3, disbursements 4, renewals 6, tax 5, clock 1). All documented query filters are implemented per endpoint (e.g. `/appointments` takes `student_id`, `department_id`, `term_id`, `renewed_from_appointment_id`, `lifecycle_status`, `payroll_status`; `/renewal-decisions` takes `decision`).

## Verification performed

- **Happy-path smoke** (`/tmp/smoke2257.py`, ~50 calls): full CALENDAR_DAY lifecycle through term close, with assertions that allocation stipend/remission splits sum exactly to the appointment totals, per-disbursement `allocation_split` sums to `gross_amount_cents`, and `authorized == available + committed + expended` after commit, pay, reverse and close.
- **Corner-case smoke** (`/tmp/smoke2257b.py`, ~50 calls, WORKDAY term): all 12 submit-battery rejections fire in PRD §2.10 priority order (`ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED`, `ERR_FUNDING_PERIOD_MISMATCH`, `ERR_COST_SHARE_SOURCE_INVALID`, `ERR_ALLOCATION_SHARES_INVALID`, `ERR_STIPEND_BELOW_MINIMUM`, `ERR_DUAL_ROLE_CONFLICT`, `ERR_OVER_APPOINTMENT`), plus effort-cap override → segregation of duties → SAP gate → approve/activate/schedule, pay suspend/resume branching, source suspend/reinstate, allocation release reverting a FUNDING_VERIFIED appointment to `RETURNED`/`FUNDING_RELEASED`, and the full terminate cascade (`TERMINATED`/`PAY_VOIDED`, disbursements `VOIDED` with gross retained, remission zeroed pre-deadline, allocations `RELEASED`, ledger identity preserved, student effort back to 0).
- **Robustness probe** (`/tmp/probe2257.py`, 60 calls): every list endpoint's pagination and enum guards, all 9 entity 404 codes, missing/unknown auth headers (401), role gates (403), malformed/non-object JSON body (422), unknown route (404), wrong method (405). Zero 5xx, every response carrying a well-formed envelope.
- **Spec cross-check**: finished auditing SCAFFOLD validations 1–40 against the code — all match, including the FTE-normalised stipend-minimum formula (`round_half_up(monthly * 100 / effort_pct)`, not `min × effort`), term-close requiring assessments in `{FINAL, SUPERSEDED}`, and `tuition_benefit_ytd_cents` summing `FINAL` assessments only.

## Notable design decisions

1. **PRD §2.10 numeric priorities win over SCAFFOLD prose** where the scaffold's submit precondition list ordered fellowship-conflict before funding-period-mismatch and omitted the policy check.
2. **`_seq` / `_mut` private counters.** The logical clock is static, so all `created_at` values tie; `_seq` (insertion order) is the deterministic sort tiebreak everywhere, and `_mut` identifies the "most recently mutated counted appointment" that defines the reference window for the persisted `total_effort_pct`.
3. **Version-bump discipline.** `update()` bumps only when a field actually changes (avoids spurious bumps in cascades over already-zeroed rows); `force_update()` where the PRD mandates an increment; causally-linked field changes are collapsed into one mutation per row per request (e.g. `recompute_student_aggregates` covers terminate's effort + YTD steps s8/s9 with a single increment).
4. **`ERR_FUNDING_SOURCE_NOT_ACTIVE` (409) reused** for suspend/reinstate/close state mismatches — the error catalogue has no dedicated FundingSource-state code.
5. **verify-funding scopes source-ACTIVE checks to PROPOSED allocations**, per priority 12's "an allocation being committed", rather than all allocations as the scaffold's prose at line 910 suggests.
6. Test servers on ports 10777/10778/10781 were shut down; no files were written inside `test_suite/`, `test_helpers/`, or any design YAML (scratch scripts live in `/tmp`).

## Step 7: Run tests and iterate — 2026-09-01T14:33:57.000Z

Clean sweep: all 8 parallel rounds passed 111/111.

## Summary

**Iterations run:** 3 (each an 8-round parallel stability sweep). Round scores: 105/111 → 109/111 → **111/111 across all 8 rounds**. No flakiness appeared in any iteration — all failures were deterministic (failing in 8/8 rounds), and the final sweep was uniformly green.

**Tests deleted:** none. Every failure traced to a test-layer bug or a single non-derivable assertion within an otherwise PRD-faithful test.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was at fault.

**Fixes applied to `implementation/`:** none. In all six cases the implementation was already the PRD-faithful side.

**Fixes applied to `test_suite/`:**

- `test_05_validation_priority_conflicts.py`, both `test_locked_term_outranks_insufficient_funding_on_verify_funding` and `test_international_hour_limit_outranks_invalid_allocation_shares_on_submit` — the secondary assertion indexed the wrong envelope level (`body["error"]["error_id"]`, a key PRD §2.2 never declares). `validate_error` returns the error payload itself, so corrected to `error["error_id"]`. The primary `error_id`/status assertions were already correct and untouched.
- `test_10_entity_round_trips.py`, `test_omitted_optional_inputs_fall_back_to_their_declared_defaults` — the request omitted `is_international`. PRD §3.2 enumerates exactly three optional student inputs (`visa_type`, `enrolled_credit_hours`, `external_weekly_hours`) and lists `is_international` among the required ones, so the implementation's `ERR_INVALID_REQUEST` was correct. Stopped popping the required field; all default-value assertions retained.
- `test_13_validations.py`, `test_a_review_opened_before_the_window_is_refused_and_admitted_afterwards` — STEP 1c split: dropped only `clock["current_utc"] == "2026-09-02T00:00:00Z"`. PRD §2.10 says merely "answers with the resulting instant as `current_utc`" and never pins the serialization, while §2.2/§2.5 make three fractional digits the house timestamp format — so echoing the input verbatim and rendering `...00.000Z` are both PRD-faithful (unique derivability broken). Every PRD-verbatim assertion (the 120-day window date, the notice deadline, `ERR_RENEWAL_WINDOW_NOT_OPEN`, `DRAFT`/`PENDING`/`revision_count`/`sap_certified`) was kept.
- `test_17_cross_cutting.py`, `test_replaying_a_superseded_appointment_version_on_a_plan_is_refused` — asserted split amounts of 180000/120000 on a **`DRAFT`** appointment's freshly replaced plan, contradicting PRD §3.4 verbatim: "New rows have `allocated_stipend_cents`, `allocated_remission_cents` and `disbursed_amount_cents` all 0." The §3.5 stipend split runs at *submission*, which never happened here. Corrected to assert 0, matching the PRD sentence.
- `test_17_cross_cutting.py`, `test_every_accepted_write_advances_the_version_by_exactly_one` — expected the term at version 2 after create + one pay period + open. PRD §3.1 has each accepted pay period recompute the term's `pay_period_count`, and §2.4 states that "This applies to derived fields as much as to input fields," making that recompute a version-incrementing mutation of the term row. Correct chain is v1 → v2 (pay period) → v3 (open); the test now pins both steps, strengthening the derived-field rule it cites.

**Note on a host-level hazard:** my first sweep's shell logs went to `/tmp/sweep1_${i}.log`, which collided with another pipeline running concurrently on this host (its output appeared in my log file). Results JSONs were unaffected, but I switched to `mktemp -d` log directories for subsequent sweeps. Worth using unique log paths in this loop generally.

## Step 8: Finalize PRD — 2026-09-01T14:43:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 455 lines; `PRD_FINALIZED.md`: 455 lines; 0.0% line delta (1 line revised in place, +1 clause).

## Changes
- **§2.10 (logical clock)** — revise — pinned the serialization of the clock endpoint's `current_utc`: it is rendered in UTC in the house ISO 8601 form with three fractional digits, not echoed back in the request's own form — `implementation/routes/clock.py:33` (`ok({"current_utc": now_iso()})`), formatter at `implementation/db.py:43-48`.

## Per-edit pre-edit search log
**Edit 1 — §2.10 `current_utc` serialization**
- (a) Subject: how the service renders an instant into a JSON timestamp string, specifically for `current_utc`, and whether `POST /_clock/set_current_utc` normalizes/echoes its input.
- (b) Impl paths enumerated (grep for `now_iso|iso(` across all `.py`, then read): the single formatter `db.iso()`/`now_iso()` (`db.py:43-48`, `"%Y-%m-%dT%H:%M:%S" + ".%03dZ"`); `db.set_clock` (`db.py:55-56`, `astimezone(timezone.utc)` — so an offset-bearing input is normalized to UTC, never echoed verbatim); `routes/clock.py:14-33` (parser accepts `Z`/`z`/offset/naive, naive treated as UTC); and every other emitter that shares the same formatter — `response.py:19` (`api_request_timestamp`), `db.insert`/`db.touch` (`created_at`, `updated_at`), `routes/terms.py:97,120` (`locked_at`, `closed_at`), `routes/disbursements.py:72,109` (`paid_at`, `reversed_at`), `routes/appointments.py:600` (`voided_at`), `routes/renewals.py:123,175` (`certified_at`, `acknowledged_at`). All produce the identical three-digit-millisecond `...Z` UTC form, so the "same form every other timestamp this service emits uses" claim holds globally.
- (c) Wording adjustments made: said "timestamp" rather than "date/field" so the many calendar-date fields (`term_start`, `notice_sent_date`, `termination_date`, `renewal_window_open_date`, `pay_date`, …) are not swept in; said "rendered in UTC" rather than "converted from the supplied offset" to stay agnostic about the parser's accepted input shapes; deliberately left the sub-millisecond behavior unstated (impl truncates via `microsecond // 1000`, but the same formatter governs all timestamps, so no operation-specific claim was needed) to keep the sentence under-determined rather than risk a false universal.

**Items requiring no PRD change** (verified impl is already the PRD-determined side, so the Step 7 fix was purely test-layer):
- `test_05` envelope-level bug — impl's error payload lives at `data.error_id` exactly as §2.2 declares (`implementation/response.py:45-51`).
- `test_10` optional-input defaults — `is_international` is a required field in impl (`implementation/routes/students.py:32`, `v.field_bool` with no `required=False`), and §3.2 already enumerates exactly three optional student inputs.
- `test_17` superseded-plan replay — replacement inserts new rows with all three cents fields at 0 (`implementation/routes/appointments.py:271-273`), matching §3.4 verbatim; the split only runs at submission.
- `test_17` version chain — appending a pay period recomputes and bumps the term (`implementation/routes/terms.py:276`), and opening bumps it again (`terms.py:82`); §3.1 plus §2.4's "applies to derived fields as much as to input fields" already forces v1 → v2 → v3.

## Step 9: Complete PRD — 2026-09-01T15:00:30.000Z

`workspace/PRD_COMPLETED.md` is written.

## Counts

- **Source:** `PRD_FINALIZED.md` — 455 lines, 90,012 chars
- **Result:** `PRD_COMPLETED.md` — 456 lines, 99,303 chars (**+1 line, +9,291 chars**)
- Structure preserved exactly: 27 headings and 113 table rows in both; no new sections. The single added line is one bullet appended to the existing §2.2 error-format bullet list.
- **Ambiguity-pins: 20 · Mismatch-revisions: 6** (26 edits total)

## Changes

- §2.1 StudentUser — revise — ambiguity — owner-restriction extended to single appointment/assessment/renewal reads; list reads auto-scope when `student_id` is omitted rather than rejecting; renewal list scopes via owned appointments and a foreign `appointment_id` yields an empty page — `routes/appointments.py:187`, `routes/tax.py:81`, `routes/renewals.py:90`
- §2.2 success envelope — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` is the logical-clock instant, not wall clock — `response.py:13`, `response.py:19`
- §2.2 error envelope — insert — ambiguity — new bullet pinning `ERR_NOT_FOUND`/404 for undefined paths, `ERR_METHOD_NOT_ALLOWED`/405, unparseable/non-object body → `ERR_INVALID_REQUEST` 422, and empty body read as `{}` — `app.py:31`, `validate.py:16`
- §2.3 pagination — revise — ambiguity — non-integer `limit`/`offset` rejected; empty-string param treated as omitted — `validate.py:165`
- §2.3 pagination — insert — ambiguity — `has_more` formula, `total_count` is the pre-window filtered count, filters are equality matches, non-existent filter value matches nothing — `validate.py:204`
- §2.3 ordering — insert — ambiguity — `created_at` ties broken by creation order, including inside the three domain orderings — `services/queries.py:53`
- §2.4 term gating — insert — ambiguity — pay-period append, and the term's own open/lock/close, report `ERR_INVALID_TERM_STATE`; policy declaration reports `ERR_TERM_NOT_OPEN`; appointment creation has no term-state rule — `routes/terms.py:74`, `routes/terms.py:255`, `routes/terms.py:210`
- §2.4 audit fields — **revise — mismatch** — a recomputation reproducing already-stored values is not a mutation (no `updated_at`/`version` bump), notably for funding sources and allocations; appointments/students always bump — `db.py:91`, `db.py:103`
- §2.6 rounding — insert — ambiguity — fractional fields rendered/accepted as JSON numbers; only `share_pct` has its decimal-place count validated — `serialize.py:79`, `routes/students.py:33`
- §2.8 stale-read — insert — ambiguity — both `expected_*_version` fields are integers ≥ 0; bad shape is 422 before the 412 — `routes/appointments.py:232`, `routes/tax.py:31`
- §2.10 item 3 — **revise — mismatch** — ownership genuinely precedes path existence only for reading one student; everywhere else the row is resolved first, so 404 precedes the 403 — `routes/students.py:69`, `routes/appointments.py:178`
- §3.1 stipend policy — **revise — mismatch** — the cap-agreement rule is unvalidated; cap is read from the term's earliest-created policy — `services/queries.py:102`
- §3.1 term read — **revise — mismatch** — "five operational roles" → the four administrative roles; `StudentUser` may not read a term — `routes/terms.py:15`
- §3.2 academic progress — revise — ambiguity — version increments unconditionally (empty/no-op payload included); no aggregate recomputation — `routes/students.py:96`
- §3.3 funding source — insert — ambiguity — all wrong-state suspend/reinstate/close rejections report `ERR_FUNDING_SOURCE_NOT_ACTIVE` — `routes/funding.py:99`, `routes/funding.py:111`, `routes/funding.py:123`
- §3.4 appointment creation — insert — ambiguity — creation imposes no term-state requirement — `routes/appointments.py:101`
- §3.4 funding plan — insert — ambiguity — replacement recomputes no appointment money field; new allocations carry zeroes — `routes/appointments.py:264`
- §3.5 effort aggregation — **revise — mismatch** — persisted student aggregate is the sum over counted appointments overlapping the most-recently-mutated counted appointment, that reference included (not "the candidate dropped") — `services/effects.py:88`
- §3.5 funding-plan battery — **revise — mismatch** — budget-window check (`ERR_FUNDING_PERIOD_MISMATCH`) runs first per §2.10 priority 24, before plan-presence/shares/cost-share/policy/fellowship; passes vacuously on an empty plan — `routes/appointments.py:327`
- §3.6 verify-funding — revise — ambiguity — both fiscal checks range over `PROPOSED` allocations only; none present passes vacuously; no money/aggregate recomputation — `routes/appointments.py:430`
- §3.6 allocation release — insert — ambiguity — the `FUNDING_VERIFIED → RETURNED` reversion recomputes no student aggregate; response body is the allocation — `routes/allocations.py:65`
- §3.6 appointment reads — insert — ambiguity — single-appointment read yields `ERR_APPOINTMENT_NOT_FOUND` ahead of the ownership 403 — `routes/appointments.py:178`
- §3.7 scheduling — revise — ambiguity — `allocation_split` covers allocations in `PROPOSED` or `COMMITTED`; empty array when none — `routes/appointments.py:507`
- §3.7 resume-pay — insert — ambiguity — guard is `payroll_status == PAY_SUSPENDED` → `ERR_INVALID_APPOINTMENT_STATE`; no lifecycle or term-state rule — `routes/appointments.py:557`
- §3.8 termination — **revise — mismatch** — stipend/remission recomputation touches only allocations in `PROPOSED`/`COMMITTED`; student effort + both YTD figures land in one mutation (one `version` bump) over the term's `tax_calendar_year` — `routes/appointments.py:612`, `services/effects.py:128`
- §3.8 renewal review — insert — ambiguity — creation imposes no appointment-lifecycle or term-state constraint — `routes/renewals.py:31`
- §3.8 acknowledge — revise — ambiguity — ownership check precedes the review's state check — `routes/renewals.py:169`
- §3.9 exemption cap — insert — ambiguity — read from the earliest-created policy, falling back to 525000 when the term has none — `services/queries.py:102`
- §3.9 close cascade — insert — ambiguity — no student row is touched and no source auto-reinstates — `services/effects.py:277`

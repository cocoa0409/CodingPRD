## Step 2: Generate Scaffold — 2026-08-15T08:55:11.000Z

All audits pass. Final lint verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    38
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  529

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/`:

**SCAFFOLD.yaml** (1382 lines) — Expert-band scaffold, `workflow_orchestration` + `compliance_audit`, flat topology, cyclic state shape, approval-chain roles with segregation of duties:
- 10 entities: PartnerAgreement, Program, Student, Application, CoursePreApproval, TravelAdvisory, InsuranceEnrollment, BillingStatement, Incident, CreditPosting
- 8 state machines; cyclic loops on Application (SUBMITTED→RETURNED_FOR_REVISION→SUBMITTED), CoursePreApproval (PENDING→NEEDS_REVISION→PENDING), BillingStatement (PARTIALLY_PAID self-loop)
- 38 endpoints including `POST /api/v1/_clock/set_current_utc` (default 2026-08-01T00:00:00Z); 26 error codes; 11 ordered validation priorities (auth → roles/ownership → existence → schema → state → segregation → safety → temporal → referential → constraint → fiscal)
- 1 OCC concurrency rule: `cpa-create-stale-application` (expected_application_version, ERR_STALE_VERSION 412) on the supersede-on-create pre-approval endpoint
- Key pinned mechanics: billing dual-variant (HOME_TUITION vs PROGRAM_FEE, aid-portability min-cap), per-course-then-sum 0.5-step credit rounding, DO_NOT_TRAVEL full-containment cascade (advisory→program→application→billing/insurance, depth 3) vs partial-overlap gating (no cascade), 7-day host schedule buffer, half-open advisory windows, credit-posting cascade (depth 2)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1154 lines) — all 9 rules × 2 instances = 18, every one with fully structured, replayable `setup_api_calls`/`trigger` chains and code-computed literal asserts (verified by executing the formulas: 940000/1540000/760000/1840000 cents; 6.5 vs 2.5 credits).

**SCAFFOLD_CORNER_DESIGN.yaml** (1743 lines) — 52 instances across 7 taxonomy sections (entities 9, state_machines 10, calculations 1+4 stubs, validations 12+5 stubs, endpoints 1, rbac 6, cross_cutting_layers 1+3 stubs); all 12 stubs cite existing difficulty instances.

Cross-checks run clean: placeholder closure (no unbound `${var}`), 70 unique instance names across the union, no dangling stub references, all 26 errors referenced, no forbidden race vocabulary, no design keys leaked into SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-08-15T08:55:35.000Z

Copied ./INSTRUCTION.md to tasks/task_2027_study_abroad_program_administration/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T09:06:25.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/workspace/PRD.md` (~5,400 words). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Document structure** (designed fresh for this domain, not copied from the example):
- §1 Introduction — 2 paragraphs, business-context angle (office reconciling academic/financial/safety obligations)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 5 roles with identity translation: `Student` entity-backed, four staff roles opaque), 2.2 Response Structure (**byte-identical** to canonical source, verified by diff), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Temporal Semantics (initial `2026-08-01T00:00:00Z`, half-open advisory windows), 2.6 Money & Credit Precision (integer cents; floor only on aid-cap product; per-course nearest-0.5 half-up rounding before summing), 2.7 Cascading Reconciliation, 2.8 Nested Resource Retrieval, 2.9 OCC (single rule, no race framing), 2.10 Validation Ordering (all 11 priority tiers with error ids)
- §3 Business Logic — 8 subsections organized chronologically (catalog → applications/clearance → course pre-approvals → commitment/billing → insurance/departure → advisories/suspension → incidents → return/credit posting), with constants embedded as business figures ($24,000 home tuition, $350 premium, $50 fee, 100%/60% aid caps, 7-day buffer, 2.0 grade floor) and parameters scattered across subsections
- §4 Endpoint table — 38 rows, 4 columns only
- §5 Error catalogue — 26 rows, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 61 required (incl. lines sub-fields course_preapproval_id/grade_points and clock output current_utc), 61 present, 0 missing
- endpoints[].request_body: 43 required, 43 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in §2.10 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (course-preapproval create + expected_application_version + ERR_STALE_VERSION/412 all named; no simultaneity framing), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed (incl. CLEARED-untouched suspension cascade, revision loops, PARTIALLY_PAID self-loop, TRIAGED→RESOLVED shortcut), 0 missing
- calculations[]: 4 checked, 4 fully expressed (billing dual-variant with floor; per-course 0.5 half-up rounding before summing; refund credit memo; seats_taken COMMITTED/ABROAD set), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (commit→statement creation, supersede cascade, void+cancel cascades, post→CREDIT_POSTED, reported_by/posted_by stamps), 0 missing
- entities[].fields[] structured content: defaults/ranges/enum membership/computed semantics all reconstructible (insurance_required=false, aid_award_cents≥0 default 0, seats_taken=0, snapshot-vs-live aid, frozen billing_model_snapshot), 0 missing
- sibling-branch symmetry: 8 groups checked (3 clearance decisions, 3 review decisions, 2×2 payment branches, 3 void sources, 2 supersede sources, 5 withdraw sources, 2 resolution paths, 2 billing variants), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 380
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: all 26 error ids appear in §2/§3 prose, all 46 enum/state values present verbatim, all 5 role names present, and §2.2 confirmed byte-identical to `section-2.2-response-structure.md`.

## Step 5: Generate Unit Tests — 2026-08-15T09:21:12.000Z

Done. Full test infrastructure generated for `task_2027_study_abroad_program_administration`.

## What was built

**`test_helpers/` (9 files)** — PRD-specific infrastructure on top of `prd_bench_local_runner.testing`:
- `types.py` — all 10 entities' TypedDicts plus status enums (all carry `common_fields: true`, so all include `id`/`created_at`/`updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (30 endpoints)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map for all 26 errors, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_billing_money_invariants`
- `factories.py` — per-entity payload factories, input fields only
- `constants.py` — billing constants (2400000 / 35000 / 5000 / cap 1.00 / 0.60), credit constants (2.0 grade min, 0.5 step), 7-day buffer, initial clock
- `test_users.py` — opaque-role shared headers + `make_student_headers` (entity-backed Student) and per-role builders; segregation-of-duties uses distinct `coord-a` / `coord-b`
- `fixtures.py` — 5-tier composite helpers: `create_open_program`, `create_cleared/approved/committed/abroad/returned_home_application`, `setup_committed_with_statement`, `setup_returned_home_with_approved_courses`, pre-approval/payment/advisory/clock helpers

**`test_suite/` (13 files, 79 tests)** — all translated strictly from the two design indices; every test docstring carries a verbatim PRD quote (C1–C3) and ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` tag (C4).

## Audit results
- **Queue A (difficulty):** all 18 non-stub instances have ≥2 tests — PASS
- **Queue B (corner):** all 41 non-stub instances have ≥1 test; all 13 `excluded_because:` stubs cross-resolve to a real difficulty instance and were not translated — PASS
- **Citation verbatim pass:** every quoted PRD sentence contains an ≥8-word substring surviving literal grep of PRD.md — 0 failures
- **Hygiene:** no `pytest.mark.skip`/`skipif`/`xfail`, no "scaffold" mentions, `python -m py_compile` clean, `pytest --collect-only` collects 79 tests

## Key design decisions
- **Segregation of duties** is threaded through fixtures: clearance recorded by `coord-a`, approval by `coord-b`, so every happy-path approval satisfies `X-User-ID != clearance_recorded_by`.
- **OCC (§2.9):** pre-approval creation re-reads the application's current `version` via `get_application_version` before each create, so the stale-version test is deterministic.
- **Logical clock:** tests needing a clock past the deadline or inside an advisory window use `set_logical_clock` (staff-only); the default clock (2026-08-01) precedes the 2026-11-01 deadline used by all fixtures.
- No instances were skipped: every non-stub instance in both queues passed the PRD-first two-condition filter (PRD §2.10's numbered validation tiers explicitly name the priority order for the two priority-pair instances, and §3.x prose names every asserted error_id, threshold, transition, and side effect).

## Step 6: Generate Implementation — 2026-08-15T09:21:12.000Z

The implementation is complete and verified. Here's the summary.

## Implementation Complete

Generated a full Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/workspace/implementation/`:

**Files:**
- `start.sh` — executable launcher, guards `pip install` behind a flask-import check (safe for per-test-server reboots), runs `app.py` via `exec` in the foreground
- `requirements.txt`, `app.py` (entry point + error handlers, binds `0.0.0.0:$PORT` default 10000)
- `db.py` — in-memory stores (empty at boot, no seeding) + logical clock pinned to `2026-08-01T00:00:00Z`
- `errors.py` — all 26 error IDs from the scaffold catalog with exact HTTP statuses
- `response.py` — envelope matching the scaffold exactly: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type` (`object`/`array`/`error`), `data` (errors carry `error_id`/`message`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5-role RBAC, student-ownership checks
- `routes/` — 11 modules covering all 30 endpoints
- `services/` — billing calc (`billing_charge_calculation` with exact constants and floor-on-aid-cap), cascades (withdrawal side effects, advisory suspension), program helpers (`seats_taken` aggregation, 7-day schedule buffer, travel-warning gate)

**Key behaviors verified by end-to-end smoke + edge tests (all passing):**
- Full lifecycle: agreement DRAFT→ACTIVE, program DRAFT→OPEN, application SUBMITTED→CLEARED→APPROVED→COMMITTED→ABROAD→RETURNED_HOME→CREDIT_POSTED
- Segregation of duties (clearer ≠ approver → 403 `ERR_SEGREGATION_OF_DUTIES`)
- OCC on course-preapproval create (`expected_application_version` mismatch → 412 `ERR_STALE_VERSION`); supersede cascade flips old PENDING/APPROVED record to SUPERSEDED and bumps parent application version
- Billing: PROGRAM_FEE math (base 1800000, premium 35000, fee 5000, aid cap floor(0.6·base), charge 760000) and HOME_TUITION math (base 2400000, cap 100%) — integer cents, payments ISSUED→PARTIALLY_PAID→PAID, overpayment/not-positive rejections, void-on-withdraw with `credit_memo_cents = amount_paid_cents`
- Travel advisories: half-open overlap rejection (adjacency allowed), DO_NOT_TRAVEL fully-containing window suspends OPEN programs and cascades SYSTEM_SUSPENSION withdrawals (billing voided, insurance cancelled, seats released), lift is non-retroactive, gate blocks approve/insurance-create with 422
- Insurance: coverage containment check, duplicate-ACTIVE rejection, cannot-cancel-while-ABROAD lock, DEPART requires covering ACTIVE enrollment
- Credit posting: per-course round-half-up-to-0.5 before summing, provisional (all lines) vs final (grade ≥ 2.0), duplicate-posting rejection, post cascades application to CREDIT_POSTED with `transfer_credits_posted = final_credits`
- Validation ordering: auth (401) → role/ownership (403) → existence (404) → body integrity (400/422 fee rule) → state (409) → SoD → safety gates → temporal → referential → domain → money/capacity
- Deadline equality (clock == deadline has NOT passed), 7-day schedule buffer (exactly 7 allowed, overlap rejected)
- Clean-boot isolation: killed and relaunched via `bash start.sh`, store comes back empty with correct error envelopes

## Step 7: Run Tests and Iterate — 2026-08-15T09:29:56.000Z

## Summary

**Result: clean 8-round parallel sweep — 79/79 passed in every round (rounds 1–8), zero failures in the union.**

### Iterations run
2 sweeps (16 total round-runs). Iteration 1 surfaced 2 deterministic failures (failed in all 8 rounds, no flakiness); both fixes landed, iteration 2 passed 8/8 rounds.

### Tests deleted
None.

### Fixes applied to `test_helpers/`
- **`factories.py` — `create_program_payload`**: when the effective `billing_model` is `HOME_TUITION` and the caller did not explicitly pass `program_fee_cents`, the inherited `PROGRAM_FEE` default (`program_fee_cents: 1800000`) is now dropped from the payload. Previously, any test overriding only `billing_model="HOME_TUITION"` built a request that PRD §2.10 tier 4 forbids ("a `HOME_TUITION` program must omit `program_fee_cents` or set it to 0 (`ERR_INVALID_REQUEST`)"), so the PRD-faithful implementation correctly rejected it with HTTP 400. This was the root cause of `test_04_billing_charge_calculation.py::TestDualVariantBilling::test_home_tuition_variant_charge` failing in all 8 rounds. Explicit `program_fee_cents` overrides are preserved so validation tests can still exercise the rejection path.

### Fixes applied to `test_suite/`
- **`test_07_travel_advisories.py`**: added the missing `create_submitted_application` import (used at line 255 but never imported → `NameError` in `TestAdvisorySuspensionCascade::test_advisory_suspension_spares_cleared_application`, failing all 8 rounds). The helper is exported from `test_helpers.fixtures`; the test's PRD §3.6 assertion (CLEARED applications survive the suspension cascade) was already faithful.

### Fixes applied to `implementation/`
None — the implementation was PRD-faithful in both failure cases; both were test-artifact bugs.

### Notes
- The runner's interleaved console stream is unreliable for failure attribution (8 concurrent pytest processes garble line boundaries — a test name from one round can merge with another round's FAILED marker); the per-round `results.N.json` files are authoritative and were used for the union.
- Pyflakes scan of `test_suite/` + `test_helpers/` confirmed no other undefined names; implementation verified as in-memory only with no seeding, per the storage contract.

## Step 8: Finalize PRD — 2026-08-15T09:32:34.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/workspace/PRD_FINALIZED.md` is written as a byte-identical copy of PRD.md.

## Summary

**Line counts / delta:** PRD.md = 275 lines; PRD_FINALIZED.md = 275 lines; 0% delta (zero edits).

**Changes made:** None — intentionally. Both `<step_7_diff>` items are test-artifact bugs where the PRD already uniquely determines the behavior and the implementation was confirmed PRD-faithful (the diff itself states: "the implementation was PRD-faithful in both failure cases"). There were no `implementation/` fixes and no test deletions, so no PRD silence or PRD/impl mismatch exists to pin.

**Per-item investigation log** (the mandatory pre-edit search; in both cases the search's outcome was "no edit warranted"):

1. **`test_helpers/factories.py::create_program_payload` fix (HOME_TUITION fee default)**
   - (a) Subject: conditional `program_fee_cents` validation on program creation by `billing_model`.
   - (b) Impl paths enumerated: `implementation/routes/programs.py:51-59` (tier-4 request validation: `PROGRAM_FEE` requires positive int else `ERR_PROGRAM_FEE_REQUIRED`/422; `HOME_TUITION` rejects non-null non-zero with `ERR_INVALID_REQUEST`, normalizes omitted to 0) and `implementation/services/billing.py:15-20` (only consumer of the stored field; reads `program_fee_cents` solely in the `PROGRAM_FEE` branch — HOME_TUITION base is the 2400000 constant). Test-side consumers grepped across `test_suite/` + `test_helpers/`: no test asserts a HOME_TUITION program's stored `program_fee_cents`.
   - (c) No wording change: PRD §2.10 tier 4 (line 116) already states verbatim "a `HOME_TUITION` program must omit `program_fee_cents` or set it to 0 (`ERR_INVALID_REQUEST`)" and §3.1 (line 131) states "`PROGRAM_FEE` programs carry a positive `program_fee_cents`, while `HOME_TUITION` programs carry none." The pre-fix factory built a request the PRD expressly forbids; the impl correctly returned 400. Pure fixture bug — PRD is not silent here, so any edit would be churn (and risks a new mismatch, e.g., over-pinning the response representation that no code path requires).

2. **`test_suite/test_07_travel_advisories.py` fix (missing `create_submitted_application` import)**
   - (a) Subject: advisory suspension cascade's selection of victim application statuses (CLEARED spared).
   - (b) Impl paths enumerated: `implementation/services/cascade.py:38-51` (`suspend_program_cascade` withdraws only `("APPROVED", "COMMITTED")` with `SYSTEM_SUSPENSION`); all `withdraw_application` callsites — `implementation/routes/applications.py:266` (manual withdraw, `STUDENT_INITIATED`/`STAFF_INITIATED`) and `cascade.py:48` (`SYSTEM_SUSPENSION`) — plus the sole cascade trigger `implementation/routes/travel_advisories.py:72`. No path anywhere withdraws CLEARED applications or sets `SYSTEM_SUSPENSION` manually.
   - (c) No wording change: PRD §3.6 (line 181) already states verbatim "every application in `APPROVED` or `COMMITTED` is withdrawn with `withdraw_reason` set to `SYSTEM_SUSPENSION`, while `CLEARED` applications are deliberately left untouched," and §3.2 (line 145) already reserves `SYSTEM_SUSPENSION` from manual calls. The failure was a `NameError` from a missing import — a pure Python test bug with zero behavioral content.

## Step 9: Complete PRD — 2026-08-15T09:44:57.000Z

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_2027_study_abroad_program_administration/workspace/PRD_COMPLETED.md`.

**Source:** `PRD_FINALIZED.md` (275 lines / 41,392 chars) → `PRD_COMPLETED.md` (281 lines / 45,416 chars); delta +6 lines, +4,024 chars. No sections added or removed; all changes are inline inserts/revisions.

**Counts:** 26 ambiguity-pins, 2 mismatch-revisions (28 changes total).

**Changes:**

- §2.2 Success envelope — revise — ambiguity — pinned `api_request_id` as `req_` + 24 lowercase hex chars — implementation/response.py:10
- §2.2 Error envelope — insert — ambiguity — undefined path or unsupported method → 404 `ERR_NOT_FOUND`; absent/malformed JSON body treated as empty object so first missing field surfaces `ERR_INVALID_REQUEST` — implementation/app.py:41-51, routes/applications.py:40
- §2.3 Pagination — revise — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` → `ERR_INVALID_REQUEST` — implementation/utils.py:77-97
- §2.3 Pagination — revise — ambiguity — sort by `created_at` asc with `id`-ascending tie-break; filters are exact-match equality, unmatched values yield empty pages, unknown query params ignored — implementation/routes/programs.py:106-118
- §2.3 Pagination — revise — ambiguity — `has_more` defined as `offset + limit < total_count`; `total_count` counts all matches — implementation/response.py:17
- §2.4 Common properties — revise — ambiguity — `version` starts at 1 at creation — implementation/routes/partner_agreements.py:50
- §2.4 Common properties — insert — ambiguity — `created_at`/`updated_at` coincide at creation; stamp fields (`clearance_recorded_by`, `approved_by`, `withdraw_reason`, `reviewed_by`, `review_notes`, `resolution_notes`, `posted_by`) born null; `transfer_credits_posted` born 0; `credit_memo_cents` born 0 — implementation/routes/applications.py:84-88, services/billing.py:43
- §2.5 Logical clock — insert — ambiguity — clock-set validates ISO 8601 (`ERR_INVALID_REQUEST`), stores the string verbatim, echoes it as `current_utc` — implementation/routes/clock.py:19-23, db.py:25-28
- §2.5 Logical clock — insert — ambiguity — offset-less ISO inputs interpreted as UTC; date-time fields stored/returned verbatim; `created_at`/`updated_at`/`api_request_timestamp` come from server wall clock, logical clock governs rule evaluation only — implementation/utils.py:14-17, db.py:11-14
- §2.9 OCC — revise — ambiguity — `expected_application_version` must be an integer (missing/null/non-integer → `ERR_INVALID_REQUEST`); comparison evaluated after body integrity, before any creation/supersession — implementation/routes/course_preapprovals.py:39,45-46
- §2.10 tier 4 — insert — ambiguity — unrecognized body fields ignored rather than rejected — implementation/routes/applications.py:40-42
- §2.10 tiers 8/9 — revise — **mismatch** — swapped referential-integrity and temporal tiers: impl checks agreement existence before the schedule buffer (routes/programs.py:62-67) and program OPEN before the deadline (routes/applications.py:58-65)
- §3.1 — revise — ambiguity — `country_code` stored as supplied, no ISO format enforcement — implementation/routes/partner_agreements.py:21
- §3.1 — revise — ambiguity — `insurance_required` must be a boolean when supplied — implementation/routes/partner_agreements.py:26-28
- §3.1 — revise — ambiguity — `program_fee_cents` must be a positive integer under `PROGRAM_FEE` (missing/non-integer/non-positive → `ERR_PROGRAM_FEE_REQUIRED`); `HOME_TUITION` stores and returns it as 0 — implementation/routes/programs.py:52-59
- §3.1 — insert — ambiguity — schedule buffer measured on exact parsed instants, 7 days = 168 hours — implementation/services/program.py:27,42-48
- §3.2 — revise — ambiguity — submission check order pinned: program exists (404) → student exists (404) → program OPEN (409) — implementation/routes/applications.py:48-59
- §3.2 — revise — **mismatch** — removed "with optional `notes`" from clearance; impl neither stores nor returns notes — implementation/routes/applications.py:132-151
- §3.2 — revise — ambiguity — resubmission re-runs no submission gates (deadline/GPA/conduct/duplicate not re-evaluated) — implementation/routes/applications.py:154-172
- §3.3 — revise — ambiguity — pre-approval creation not gated on application status — implementation/routes/course_preapprovals.py:24-49
- §3.3 — revise — ambiguity — revision leaves `course_title` unchanged when omitted and retains prior `reviewed_by`/`review_notes`; review/revise not gated on parent application status — implementation/routes/course_preapprovals.py:105-167
- §3.4 — insert — ambiguity — commit response returns the updated application object (not the statement) — implementation/routes/applications.py:246
- §3.5 — revise — ambiguity — recording departure changes neither `seats_taken` nor program `version` — implementation/routes/applications.py:302-306
- §3.5 — revise — ambiguity — `Student`-role enrollment lists scoped to own applications' enrollments — implementation/routes/insurance_enrollments.py:96-102
- §3.6 — insert — ambiguity — travel gate overlap uses inclusive boundaries (`effective_from` ≤ `end_date` and `effective_to` ≥ `start_date`; an advisory whose `effective_to` equals `start_date` still blocks) — implementation/services/program.py:73-74
- §3.8 — insert — ambiguity — `lines` presence/array-typedness checked before the `RETURNED_HOME` gate; per-line element validation after it; empty `lines` accepted with zero totals — implementation/routes/credit_postings.py:29-35,42-77
- §3.8 — insert — ambiguity — whole-number credit totals serialized as integers (`3` not `3.0`) — implementation/routes/credit_postings.py:79-81,91-92

**Notable findings:** the two true mismatches were (1) the §2.10 validation-ordering tiers placed temporal rules before referential integrity, while the implementation consistently resolves body-referenced entity existence/state first; (2) the PRD described optional clearance `notes`, which the implementation accepts silently but neither stores nor returns, so the mention was removed. Everything else was PRD silence pinned to the implemented behavior.

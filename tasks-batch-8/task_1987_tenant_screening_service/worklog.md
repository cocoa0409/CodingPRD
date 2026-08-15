# Worklog — task_1987_tenant_screening_service

## Step 1: Create Task Directory — 2026-08-15T04:56:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1987_tenant_screening_service/` and `workspace/` already existed; no new index computed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-15T05:54:00.000Z

All checks pass. The scaffold package is complete and clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys leaked)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**

| Element | Count |
|---|---|
| Entities | 12 (Landlord, JurisdictionRule, ScreeningCriteria, Applicant, ScreeningApplication, ScreeningReport, ScreeningRecord, IncomeVerification, Guarantor, AdverseActionNotice, Dispute, ConsistencyAuditRun) |
| State machines | 8 (incl. parallel `status` × `identity_status` dimensions on ScreeningApplication, a cyclic report dispute/redelivery loop, branching dispute machine) |
| Calculations | 8 (rent_to_income_ratio with SOI variant, guarantor_qualification with policy variants, screening_recommendation decision table, screening_fee with pinned round-per-component order, record_suppression_sweep, compliance_windows, consistency_audit, identity_verification_threshold) |
| Endpoints | 47 (incl. `POST /api/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default) |
| Error codes | 33 |
| Validations rows | 12 (ordered priorities; resource-state at 6 before cross-entity state at 7, safety 8, temporal 9, constraint 10, referential 11) |
| Roles | 4 (ComplianceAdmin/Screener opaque; Landlord/Applicant entity-backed; segregation-of-duties on dispute reinvestigation) |
| Concurrency rules | 1 (OCC on `Landlord.version` for criteria publish, 412 `ERR_STALE_VERSION`) |
| §1.8 instances | 18 (9 rules × 2, all differentiation clauses honored — e.g., dual variants on income vs guarantor domains, combinatorial modes (a) decision-table vs (b) nested-rounding, cascades depth-4 vs depth-3 from different triggers, state-vs-safety and temporal-vs-referential priority pairs, half-open vs closed interval overlap, record-count vs money conserved quantities) |
| §1.9 instances | 48 entries = 45 active + 3 `excluded_because` stubs, across 8 sections |

**Verification:** `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(856 calls scanned: 47 endpoints, 12 entities, 18 §1.8 + 45 §1.9 active instances.) Additionally verified: instance-name uniqueness across both design files (66 unique), no forbidden concurrency vocabulary, all `grounds:` references resolve to declared §1.1–§1.7 elements, stubs cite existing difficulty instances, and every error code is exercised by at least one instance. All formula-derived asserts were pre-computed as literals (e.g., fee 3439 = 2500 + 313×3 per-component rounding vs the 3438 sum-then-round alternative; guarantor thresholds 600000/800000; audit rate 0.3333).

## Step 3: Copy Shared Files — 2026-08-15T05:56:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1987_tenant_screening_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T06:10:00.000Z

All checks pass. Here is the final report.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/workspace/PRD.md` — 308 lines.

**Section list:**
- §1 Introduction (2 paragraphs: regulatory/FCRA-style business context + bureau operating model)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block, byte-for-byte verified) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Request Validation Order · 2.7 Money, Rounding, and the Screening Fee Ledger · 2.8 Optimistic Concurrency Control on Criteria Publication
- §3 Business Logic & Workflows (9 subsections): 3.1 Bureau Setup: Landlords, Jurisdiction Rules, and Screening Criteria · 3.2 Applicant Intake, Consent, and Identity Verification · 3.3 Submission, Criteria Pinning, and Portable Screening Reports · 3.4 The Bureau Search: Records, Suppression, and the Screening Fee · 3.5 Income Verification and Guarantor Evaluation · 3.6 Scoring, Delivery, and the Landlord's Decision · 3.7 Withdrawal, Suspension, and Fee Refunds · 3.8 Adverse Action Notices and Dispute Filing · 3.9 Reinvestigation, Correction Cascades, and Consistency Audits
- §4 Endpoint Definitions (all 47 scaffold endpoints, 4-column table)
- §5 Error Code Catalogue (all 33 errors, 2-column table)

**Hard Contract results (all PASS):**
- Contract 1 Field-Name Coverage: `entities[].fields` 81 required / 81 present / 0 missing; `endpoints` input+query+path identifiers 52 required / 52 present / 0 missing.
- Contract 2 Rule Coverage: 12 validation priorities expressed as an explicitly ordered pipeline in §2.6 (with pinned sub-orders: consent before identity; the submit-time structural trio in relative order); 1/1 OCC rule expressed (`expected_landlord_version` non-optional on criteria publish, mismatch → `ERR_STALE_VERSION` 412, no other endpoint takes a version field); 30/30 state transitions across 8 machines expressed with preconditions + error ids + side effects; 8/8 calculations expressed in precise prose (constants 70, 3 attempts, 2500/0.125/313/1000 cents, 7-year lookback defaults, 30-day windows ×3, round-each-component-then-sum-then-cap order with the 3438-vs-3439 pinned-order note from the scaffold); 33/33 error ids paired with trigger conditions in §2/§3 prose; 47/47 endpoint side effects covered; cross-entity cascades (suspension, withdrawal refund, dispute file, UPHELD restore, CORRECTED 3-hop recompute with `requires_reconsideration`) all stated; field defaults/nullability reinforced by a §2.5 lifecycle-null convention sentence; sibling branches (withdraw/cancel quads, decide pair, guarantor variants, resolve outcomes, deliver pair, 6-branch recommendation, 5 reason codes) rendered with equal density.
- Contract 3 §3 Path Purity: 464 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. All §3 endpoint references use state-transition framing, role + action verb, or capability description.

**Scaffold-section coverage audit (§1.1–§1.7):**
- §1.1 Entities (12): all described in §3.1–§3.9 with every field name backticked; `ConsistencyAuditRun`'s `common_fields: false` (id + created_at only, no `updated_at`/`version`) stated in §2.5 and §3.9.
- §1.2 State machines (8) + concurrency rule: all transitions, preconditions, and side effects in §3; OCC rule in §2.8; `ERR_APPLICATION_TERMINAL` vs `ERR_INVALID_APPLICATION_STATE` split stated per transition.
- §1.3 Calculations (8): rent-to-income standard + SOI-adjusted variants, guarantor independent/combined variants, 6-branch recommendation table, tiered fee with cap semantics, suppression sweep with strictly-older-than boundary, 30-day compliance windows (inclusive bounds), consistency audit aggregation (4-decimal round-half-up, zero-when-empty), identity threshold — all in §3.2–§3.9 and §2.7.
- §1.4 Validations (12 priorities): ordered pipeline in §2.6; per-rule trigger prose beside each workflow in §3; priority-12 "no blocking fiscal validations" stated in §2.6 stage 12 and §2.7.
- §1.0 Envelope: §2.2 emitted verbatim (byte-for-byte match verified against `section-2.2-response-structure.md`); pagination defaults (limit 10/1/100, offset 0, `created_at` ascending, meta fields) in §2.3.
- §1.5 Endpoints: all 47 in the §4 table with method, path, description, and authorized roles only.
- §1.6 Errors: all 33 in §5 (2 columns), each also mentioned with its trigger in §2/§3 prose.
- §1.7 Roles: all four roles with exact spelling in §2.1, with identity translation (ComplianceAdmin/Screener opaque; Landlord/Applicant entity-backed with the foreign-key comparison rule) and read-scoping rules.

One scaffold-internal inconsistency was handled deliberately: validation priority 10 lists HTTP 409 for its whole group, but the §1.6 error catalog assigns 422 to `ERR_PORTABLE_REPORT_INVALID` and `ERR_PORTABLE_REPORT_NOT_ACCEPTED`. The PRD follows the catalog (§5 shows 422 for both) and §2.6 stage 10 now notes the split explicitly.

## Step 5: Generate Unit Tests (attempt 1) — 2026-08-15T06:25:00.000Z

**PREMATURE EXIT — no artifacts written.** The subagent returned after producing only an instance inventory (18 queue-A instances, 39 non-stub queue-B instances) and the note "let me start writing `test_helpers/`". On-disk verification: neither `test_helpers/` nor `test_suite/` exists. Attempt 1 discarded; Step 5 re-spawned below.

## Step 6: Generate Implementation — 2026-08-15T06:25:00.000Z

Done. The complete implementation is in place and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/workspace/implementation/`):

- `start.sh` — foreground launcher, guarded `pip install` (no-op when Flask is already importable), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2,<4.0`
- `app.py` — entry point, blueprint registration, error handlers (`ApiError` → envelope; 404/405 → `ERR_NOT_FOUND`; unexpected → `ERR_INVALID_REQUEST`)
- `db.py` — in-memory `Store`; logical clock defaults to `2026-08-01T00:00:00Z`; no seeding anywhere
- `errors.py` — all 33 error IDs from the scaffold catalog with their HTTP statuses
- `response.py` — exact envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (3-fractional-digit ISO 8601 UTC), `response_type` (`object`/`array`/`error`), `data`; list pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, role admission, Landlord/Applicant entity-backed ownership checks
- `util.py` — logical clock, datetime parse/format, request body validators (`ERR_INVALID_REQUEST`), pagination (default 10, min 1, max 100, offset 0), common-field stamping (`id`/`created_at`/`updated_at`/`version`), serializers
- `services/core.py` — jurisdiction-rule half-open overlap, covering-rule lookup, closed-window criteria pinning, suppression sweep (strictly-older-than, calendar-date cutoffs, `SEARCH_PROHIBITED` when criminal lookback = 0), pinned fee rounding (round each 0.125×2500 surcharge to 313 first, then sum, then inclusive cap), SOI-adjusted and standard affordability, recommendation decision table, withdraw/suspend cleanup cascade, portable temporal/structural checks
- `routes/setup.py`, `routes/applications.py`, `routes/people.py`, `routes/reports.py`, `routes/disputes.py`, `routes/notices.py`

**Endpoint count: 38 implemented** — every row of the scaffold endpoint table (clock, 3 landlord, 2 jurisdiction-rule, 5 criteria, 1 applicant, 10 application actions incl. consent/verify-identity/submit/record-searches/withdraw/score/decide, 4 guarantor, 5 income-verification, 3 report, 2 record, 5 dispute, 4 adverse-action-notice, 2 consistency-audit).

**Boot smoke-check results:**
- `bash start.sh` boots cleanly; confirmed twice in a row — second fresh process returned `ERR_NOT_FOUND` for a landlord created in the first boot, proving empty-store restart for `--isolation per-test-server`.
- 48-check end-to-end smoke passed: full pipeline intake → identity (inclusive 70 threshold, 3-attempt cap, VERIFIED terminal) → consent → submit → search (criminal-prohibited CA rule: fee 3126 capped to 3000) → score → deliver → DENY with derived `EVICTION_RECORD` notice → dispute → segregation-of-duties → CORRECTED cascade flipping recommendation to `RECOMMEND_APPROVE` with `requires_reconsideration=true` → rescind → consistency audit (`deviation_rate` 1.0, 4dp half-up, no `updated_at`/`version`).
- 20-check second suite passed: pinned 3-type fee = 3439 (not 3438), portable copy creation with re-swept records and inherited originator, 1000-cent flat fee, `ERR_PORTABLE_SEARCH_FORBIDDEN`, withdraw refund net-zero for undelivered vs no refund after delivery, `fee_charged_cents` never decremented, portable expiry at day 31 rejected / exactly day 30 accepted, ownership-scoping 403.
- 5-check third suite passed: fresh-boot empty store, SOI-adjusted affordability (voucher reduces applicable rent), voucher ≥ rent auto-pass, COMBINED_ALLOWED guarantor pooling with inclusive threshold.

## Step 5: Generate Unit Tests (attempt 2 — SUCCESS) — 2026-08-15T06:55:00.000Z

Task complete. All files written to disk, all syntax-checked, and the coverage/verbatim audits pass.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/test_helpers/`**
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — status enums (Landlord/Criteria/Application/Identity/Report/Record/IncomeVerification/Guarantor/Notice/Dispute), Recommendation/Decision/AdverseReasonCode, UserRole, 12 entity TypedDicts (ConsistencyAuditRun omits `updated_at`/`version` per `common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (34 methods) + module-level `api_client`
- `api_errors.py` — `ApiErrorId` enum (33 errors) + `HTTP_STATUS_CODES` map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` helpers incl. `assert_audit_run` (forbids `version`/`updated_at`)
- `factories.py` — payload factories for all creatable entities + workflow payloads
- `constants.py` — thresholds (identity 70/3, fee 2500/0.125/313/1000, lookbacks 7/7, windows 30d), fee test defaults, canonical clocks, criteria window
- `test_users.py` — `TEST_USERS` (admin, screeners scr-1/2/3 for segregation-of-duties, fallbacks) + `make_landlord_headers`/`make_applicant_headers`/`make_screener_headers` per-instance builders
- `fixtures.py` — composite helpers: `set_clock`, `create_landlord`, `create_jurisdiction_rule`, `create_applicant`, `create_published_criteria`, `create_application`, `consent_application`, `verify_identity`, `submit_application`, `run_record_searches`, `create_and_resolve_income_verification`, `score_application`, `deliver_report`, entity getters/listers, `setup_landlord_with_criteria`, `setup_application_flow` (through SCORED + delivered report), `setup_submitted_application`, `setup_draft_application`

**`/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/test_suite/`**
- `conftest.py` — session `api` fixture + per-role header fixtures
- `test_01_scoring_variants.py` — 6 tests
- `test_02_fees_and_suppression.py` — 4
- `test_03_state_machines_and_identity.py` — 4
- `test_04_cascades.py` — 4
- `test_05_priority_and_boundaries.py` — 18
- `test_06_entities_and_listing.py` — 6
- `test_07_state_machine_corners.py` — 10
- `test_08_calculation_corners.py` — 6
- `test_09_validation_corners.py` — 18
- `test_10_rbac_errors_and_consistency.py` — 5

**81 test functions total.** Coverage verified programmatically against the two design yamls: all 18 difficulty instances have exactly 2 tests tagged `Design: Difficulty/<rule_id>/<name>`; all 45 non-stub corner instances have exactly 1 test tagged `Design: Corner/<section>/<name>`. A docstring audit (AST-parsed) confirms every test carries exactly one Design tag and every quoted PRD citation survives whitespace-normalized verbatim match against `workspace/PRD.md` (initial audit caught 25 citations with fused/elided sentences; all were rewritten to verbatim PRD text and re-audited to 0 failures).

**Skipped instances:** none. All 18 difficulty instances and all 45 non-stub corner instances passed the PRD-first two-condition filter. The 3 corner `excluded_because:` stubs (`cascade_chains_covered_by_difficulty`, `dual_variant_layer_covered_by_difficulty`, `threshold_boundaries_covered_by_difficulty`) were not translated, per spec — their cross-references resolve to real difficulty instances (`dispute_correction_cascade_reopens_decision`, `soi_adjusted_ratio_vs_standard_ratio`, `income_ratio_exact_threshold_passes`), which are covered.

**Syntax check:** `python3 -m py_compile` passes over all 9 `test_helpers/` files and all 11 `test_suite/` files.

## Step 6: Test/fix iteration loop (8-round parallel stability sweeps) — 2026-08-15

- **Sweep 1:** collection failure — `test_07`/`test_09` could not import `get_income_verification` (missing from `test_helpers/fixtures.py`; only 2 collection errors ran per round).
- **Fix (test_helpers):** added `get_income_verification(verification_id)` getter to `test_helpers/fixtures.py` (wraps `api_client.get_income_verification`, PRD §4 `GET /api/income-verifications/{id}`).
- **Sweep 2:** 74/81 in all 8 rounds; 7 deterministic failures, all the same root cause — tests asserted exact timestamp strings without fractional digits (`...T00:00:00Z`) while the implementation uniformly serializes with three fractional digits (`...T00:00:00.000Z`).
  - `test_landlord_creation_applies_system_defaults` (test_06): PRD §2.5 verbatim requires `created_at` to have "three fractional digits" → the test contradicted PRD; fixed to expect `2026-08-01T00:00:00.000Z` (uniquely derivable).
  - 6 event-stamp assertions (`suspended_at` in test_04; `effective_from` echo and `last_delivered_at` in test_05; `issued_at`/`dispute_deadline`/`rescinded_at` in test_07; `published_at` in test_10; `consent_signed_at` in test_06): PRD covers the instant rule ("stamped with the clock", "thirty days after issue") but is silent on serialization format for non-common fields → STEP 1c partial coverage; kept instant-equality via new `assert_same_instant` helper, dropped format-equality.
- **Fix (test_helpers):** added `assert_same_instant(actual, expected_iso)` to `test_helpers/assertions.py` (Z-tolerant parse, compares instants; also asserts ISO 8601 shape).
- **Sweep 3:** 81/81 in ALL 8 parallel rounds. Exit condition met.
- No implementation changes were needed; no tests deleted.

## Step 7: Run Tests and Iterate — 2026-08-15T07:15:00.000Z

All 8 parallel rounds pass 81/81. Exit condition met.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each)
- Sweep 1: 2 collection errors per round (whole suite blocked from collecting)
- Sweep 2: 74/81 per round; 7 deterministic failures (identical across all 8 rounds — no flakiness)
- Sweep 3: **81/81 in all 8 rounds — clean exit**

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/test_helpers/fixtures.py` — added the missing `get_income_verification(verification_id)` getter. Two test modules imported it but only the `api_client` method existed; this was a pure collection blocker.
- `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/test_helpers/assertions.py` — added `assert_same_instant(actual, expected_iso, label)` (Z-tolerant ISO 8601 parse, compares instants). PRD pins the *instant* of event stamps ("stamped with the clock", "thirty days after issue") but is silent on the serialization format of non-common timestamp fields; the helper keeps the PRD-covered instant assertion while dropping the uncovered format assertion (STEP 1c split).

**Fixes applied to `test_suite/` (7 tests, all one root cause):** tests asserted exact timestamp strings without fractional digits (`2026-08-01T00:00:00Z`) while the PRD-conformant implementation uniformly serializes datetimes with three fractional digits (`2026-08-01T00:00:00.000Z`).
- `test_06_entities_and_listing.py::test_landlord_creation_applies_system_defaults` — PRD §2.5 *verbatim requires* three fractional digits on `created_at`; the test contradicted PRD. Fixed to expect `2026-08-01T00:00:00.000Z` (uniquely derivable: startup clock + pinned format).
- 6 event-stamp assertions switched to `assert_same_instant` (PRD covers the instant, not the string format — STEP 1b two-reader divergence on format): `consent_signed_at` (test_06), `suspended_at` (test_04), echoed `effective_from` and `last_delivered_at` (test_05), `issued_at`/`dispute_deadline`/`rescinded_at` (test_07), `published_at` (test_10).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout (PRD §2.5 mandates three fractional digits on `created_at`/`updated_at`, and uniform serialization is a faithful reading for the format-silent event stamps).

**Feedback notes for generators:** the unit-test generator emitted exact-string equality on timestamp fields whose format PRD leaves unpinned (a format-silence unique-derivability miss); for `created_at` it emitted an expectation contradicting PRD's explicit three-fractional-digit rule. Generator should compare instants for event stamps and honor §2.5's format for common fields.

## Step 8: Finalize PRD — 2026-08-15T07:30:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1987_tenant_screening_service/workspace/PRD_FINALIZED.md` is written.

## Summary on exit

**Line counts:** PRD.md = 307 lines; PRD_FINALIZED.md = 309 lines; delta = +2 lines (+0.65%). One insertion, zero revisions, zero deletions.

### Changes

- **§2.5 (Common Resource Properties)** — insert — new paragraph after the `version` bullet pinning that every datetime-valued field in a response is serialized as an ISO 8601 UTC timestamp with three fractional digits and a `Z` suffix, explicitly covering lifecycle event stamps and computed deadlines (all 14: `consent_signed_at`, `submitted_at`, `published_at`, `delivered_at`, `last_delivered_at`, `decided_at`, `suspended_at`, `issued_at`, `dispute_deadline`, `filed_at`, `reinvestigation_deadline`, `resolved_at`, `rescinded_at`, `run_at`), echoed window endpoints (`effective_from`, `effective_to`), stored date fields (`dob`, `record_date`), and the `current_utc` echo, with the startup-clock example `2026-08-01T00:00:00.000Z` — `implementation/util.py:20-27` (`fmt_dt`), `util.py:196-206` (`serialize`, isinstance-driven), `util.py:209-214` (`serialize_audit`), `response.py:14-17` (`_now_iso`), `routes/setup.py:44` (`current_utc`).

### Step-7 diff item disposition

- `test_helpers/fixtures.py` missing `get_income_verification` getter — pure fixture bug (collection blocker); no PRD silence → **no PRD edit**.
- `test_06` landlord `created_at` fixed to `2026-08-01T00:00:00.000Z` — PRD §2.5 already pinned three fractional digits; test contradicted PRD → **no PRD edit** (prose kept verbatim).
- `assert_same_instant` helper + 6 relaxed event-stamp assertions — one root cause: PRD pinned the format only for `created_at`/`updated_at`/`api_request_timestamp` and was silent on all other datetime fields, while the implementation serializes them all uniformly with three fractional digits → **the single §2.5 insertion above**.

### Per-edit pre-edit search log

**Edit 1 (the only edit) — §2.5 uniform datetime serialization sentence**

- **(a) Subject:** output serialization format of datetime-valued fields in API responses.
- **(b) Impl paths enumerated and read/grepped:**
  - Formatter: `util.py:20-27` `fmt_dt` (`%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`; `None` passes through as `null`); `response.py:14-17` `_now_iso` (identical format, `api_request_timestamp` — already pinned in §2.2 line 43).
  - Serializer: `util.py:196-206` `serialize` applies `fmt_dt` to *any* `isinstance(v, datetime)` value on every entity; `_DT_FIELDS` (util.py:187-193) is defined but never consulted — uniformity is structural, not field-gated. `util.py:209-214` `serialize_audit` delegates to `serialize`.
  - Response callsites (grep-verified, ~40): every `success_object`/`success_list` in `routes/{applications,disputes,notices,people,reports,setup}.py` wraps `serialize()`/`serialize_audit()` output; the only non-serialize payload is `setup.py:44` `current_utc`, which uses `fmt_dt` directly.
  - Stamp sites (all `clock()` datetimes): consent `applications.py:177`, submit `:269`, decide `:508`, deliver/re-deliver `reports.py:90-91,100`, suspend `setup.py:87`, publish `setup.py:283`, issue + `dispute_deadline` `notices.py:150`, rescind `notices.py:169`, file + `reinvestigation_deadline` `disputes.py:105-106`, resolve `disputes.py:220`, audit `run_at` `notices.py:212`.
  - Input-echo datetime fields: `effective_from`/`effective_to` (rule/criteria creation, `setup.py`), `dob` (`setup.py:318→327`), `record_date` (`applications.py:362→389` and portable copy `:293`) — all parsed by `parse_dt` into datetimes, so all echo in the same format (a bare-date input like `1990-05-15` echoes as `1990-05-15T00:00:00.000Z`).
  - Negative checks: no plain `date` object is ever stored (`.date()` at `services/core.py:128` is comparison-only), so Flask's default date serializer can never fire; `middleware.py`, `app.py`, `db.py`, `errors.py` contain no response-body datetime handling; deadline math (`disputes.py:106`, `notices.py:150`, `core.py:280`) is `timedelta` on datetimes → same formatter.
- **(c) Wording adjustment:** the universal claim ("every datetime-valued field in a response") is safe because serialization is isinstance-driven and the enumeration found zero deviations. The field examples exhaust `_DT_FIELDS` (18/18) plus `current_utc`; `api_request_timestamp` is intentionally left unnamed (§2.2 already pins it, and the universal sentence is consistent with that pin). Wording is scoped to *responses* ("serialized", "echo") so request-side parsing (`parse_dt` accepts any ISO 8601, with offsets) is not constrained, and it does not touch §2.4's instant-level prose `2026-08-01T00:00:00Z` — the added startup example describes only the *serialized stamp*, same instant, matching `test_06`'s corrected assertion.

## Step 9: Complete PRD — 2026-08-15T07:50:00.000Z

The diff is exactly as designed — 16 inline hunks, no new sections, no restructuring. Final verification of the deliverable is complete.

## Summary

**Files**: `workspace/PRD_FINALIZED.md` (309 lines / 53,246 chars) → `workspace/PRD_COMPLETED.md` (310 lines / 56,258 chars). Delta: **+1 line, +3,012 chars**, 16 hunks, all in-paragraph inserts/revisions.

**Counts**: 14 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl source):

- §2.1 — revise — **mismatch** — replaced vague "Applicant sees only their own applicant scope" with the exact scoping impl applies: Landlord scoped to own landlord record + anything referencing its `landlord_id` or hanging off its applications; Applicant scoped to own applications + dependent resources, with unrestricted reads of jurisdiction rules, criteria, landlord records, and audit histories — `middleware.py:47-64`, `routes/setup.py:143-153,204-230`, `routes/notices.py:222-236`
- §2.2 — revise — ambiguity — `api_request_timestamp` is generated from the server wall clock, the one timestamp not driven by the §2.4 logical clock — `response.py:14-17`
- §2.2 — insert — ambiguity — undefined path / unsupported method answered with `ERR_NOT_FOUND` (404) in the standard error envelope — `app.py:32-39`
- §2.3 — revise — ambiguity — non-integer or out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (not clamped); `total_count` = post-filter/pre-pagination count; `has_more` = `offset + page size < total_count`; `created_at` ties broken by insertion order — `util.py:131-159`, `response.py:42-54`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation; the immediate suppression classification is a separate mutation, so a freshly created record is first observable at `version` 2 — `util.py:166-180`, `services/core.py:122-134`
- §2.5 — insert — ambiguity — added `eviction_included_count`/`criminal_included_count` to the null-until-scoring enumeration — `routes/applications.py:127-128,467-468`
- §2.6 stage 1 — revise — **mismatch** — body-malformation (`ERR_INVALID_REQUEST`) is evaluated when the operation first consumes the payload — always after header and role stages, and after any existence/ownership/from-state/compliance checks the endpoint performs first (impl validates bodies after `require_role` everywhere, and e.g. after the terminal check in guarantor creation); unrecognized body fields ignored — `routes/applications.py:190-193`, `routes/people.py:57-63`, `routes/notices.py:127-134`
- §3.1 — insert — ambiguity — criteria creation: acting landlord id with no Landlord record fails `ERR_NOT_FOUND` — `routes/setup.py:165-167`
- §3.2 — revise — ambiguity — application creation: same `ERR_NOT_FOUND` gate before the `ACTIVE` check — `routes/applications.py:104-108`
- §3.2 — insert — ambiguity — consent on a terminal application rejected `ERR_APPLICATION_TERMINAL`; re-signing permitted and re-stamps `consent_signed_at` — `routes/applications.py:170-179`
- §3.3 — insert — ambiguity — a never-delivered portable source report (no `last_delivered_at`) is not "expired"; it is rejected at the structural stage with `ERR_PORTABLE_REPORT_INVALID` — `services/core.py:269-298`
- §3.4 — insert — ambiguity — lookback cutoff maps a Feb 29 clock date to Feb 28 in a non-leap target year — `services/core.py:96-103`
- §3.5 — insert — ambiguity — guarantor evaluation on a never-submitted application (no pinned criteria): null `qualification_policy_used`, guarantor `DECLINED` — `routes/people.py:131-157`
- §3.7 — insert — ambiguity — withdrawal `reason` accepted but not persisted — `routes/applications.py:417-429`
- §3.7 — insert — ambiguity — suspending an already-`SUSPENDED` landlord is a 200 no-op (no re-stamp, no repeated cascade) — `routes/setup.py:85-97`
- §3.8 — insert + revise — ambiguity — empty `disputed_record_ids` list accepted; only named records currently `INCLUDED` flip to `DISPUTED` (others keep status) — `routes/disputes.py:64-68,116-120`

**Notable non-changes** (verified consistent, no edit needed): submit-time portable-report existence check is unobservable dead code (existence already guaranteed at creation, no delete endpoint), so the PRD's "existence stage" phrasing stands; fee rounding/cap order, decision-table order, suppression boundary, OCC pipeline order, and all endpoint/role rows in §4 match impl exactly.

**Pipeline complete.** Final state: 81/81 tests passing in all 8 rounds of the final stability sweep; `workspace/PRD_COMPLETED.md` exists.

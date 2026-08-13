# Worklog — task_1434_employment_background_screening_vendor

## Step 1: Create Task Directory — 2026-08-13T06:42:00.000Z

Directory `tasks/task_1434_employment_background_screening_vendor/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; treated as DONE per invocation instructions. No index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T07:46:00.000Z

All three artifacts are generated and lint-clean. 

## Summary — task_1434_employment_background_screening_vendor

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: 14 (ScreeningVendor, VendorAccuracyAudit, ScreeningPackage, JurisdictionRule, AdjudicationMatrix, Position, Candidate, ScreeningOrder, ConsentRecord, ScreeningReport, ReportFinding, IndividualizedAssessment, AdverseActionCase, Dispute)
- State machines: 12 (ScreeningOrder is parallel dimensions fulfillment × adjudication; cyclic machines on ScreeningReport, AdverseActionCase, ScreeningVendor, ConsentRecord re-entry)
- Calculations: 12 (business-hours SLA, business-day adverse wait with dispute-hold extension, lookback considerability with salary exemption, first-match-wins matrix evaluation, dual-variant fees, pooled-rounding vendor accuracy, re-screen sweep selector, capacity invariant)
- Endpoints: 53 (includes `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z — a Saturday, exercising weekend clipping)
- Error catalog: 44 codes, all referenced by at least one §1.8/§1.9 instance
- Roles: 7 (HRAdmin, HiringManager, Candidate, VendorAgent, Adjudicator, ComplianceOfficer, Auditor) — Candidate/VendorAgent are entity-backed with ownership checks; segregation-of-duties: final adverse notice issuer must differ from the initiating Adjudicator
- §1.8 instances: 19 (9 rules × 2, plus a third boundary-precision instance for the 200-bps audit threshold)
- §1.9 instances: 58 total, 54 non-stub, 4 `excluded_because` stubs pointing at §1.8 instances
- Concurrency: 2 OCC rules (PUT /screening-packages, PATCH /jurisdiction-rules, both 412 ERR_STALE_VERSION)

**Lint**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (53 endpoints, 14 entities, 923 calls scanned). Three FK_REVERSE_UNREACHABLE findings were fixed by adding `GET /positions` (package_id filter) and `pinned_package_id?`/`pinned_matrix_id?` filters on `GET /screening-orders`.

**Notable design decisions**
- Cross-cutting compliance interaction: ban-the-box gate (order creation) × lookback/salary-exemption filter (finding considerability) × matrix first-match adjudication × FCRA/jurisdiction max() wait — four rules chain across different entities before an adverse path can complete.
- Dual variants in genuinely different domains: order fee (provisional vs final with 10% SLA credit, 25000 → 22500) and vendor accuracy (finalized-only 9900 vs including-draft 9733 bps).
- Combinatorial modes (a) and (b): first-match-wins rule ordering vs pinned pooled-then-rounded bps (9000 vs forbidden 9167).
- Two depth-3 cascades from different triggers: dispute-resolve-AMENDED → report AMENDED → order re-eval against the *pinned* (possibly retired) matrix → case ABORTED; consent revoke → order CANCELLED → case ABORTED → IA VOID.
- Compensating invariants on different quantities: vendor capacity slots (dispatch↔cancel) and receivable cents (provisional fee voided).
- All date/rounding literals were executed and verified in Python before being pinned in asserts (e.g., earliest final notice 2026-08-12T00:00:00Z, hold extension 3 days → 2026-08-17T00:00:00Z).
- Endpoint count (53) exceeds the Expert guideline band (20–32) deliberately, per the user's maximum-difficulty instruction; the skill's counts are guidelines, and the floors (≥6 entities, ≥12 endpoints) are exceeded.

## Step 3: Copy Shared Files — 2026-08-13T07:48:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1434_employment_background_screening_vendor/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T08:05:00.000Z

(First subagent invocation exited prematurely without writing PRD.md; resumed via SendMessage and completed on continuation.)

All checks pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/workspace/PRD.md` — 319 lines, 6,865 words. The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**PRD section list**:
- §1 Introduction (3 paragraphs: compliance, vendor accountability, segregation-of-duties framing)
- §2 Global Specifications (2.1 RBAC with per-role identity translation; 2.2 verbatim fixed response-envelope block; 2.3 Pagination; 2.4 Logical Clock & Business-Time Arithmetic; 2.5 Common Resource Properties; 2.6 Monetary Values, Precision & Rounding; 2.7 Optimistic Concurrency Control; 2.8 Validation Ordering & Left-to-Right Existence; 2.9 Parallel State Dimensions & Cascades)
- §3 Business Logic & Workflows — 11 subsections organized by lifecycle stage (catalog config → positions/candidates/orders → consent → dispatch/SLA → report delivery → adjudication → waiting period/final notice → cancellation cascades → disputes → vendor lifecycle → audits/re-screen sweep)
- §4 Endpoint Definitions — 53 endpoints, 4-column table only
- §5 Error Code Catalogue — 44 error IDs, 2-column table only

**Zero-Silence coverage confirmation** — every scaffold §1.1–§1.7 rule is rendered in PRD prose:

- **Contract 1 (Field-Name Coverage): PASS** — 97 required identifiers (all `entities[].fields[].name` across all 14 entities, plus every endpoint input/query/path param including `to_iso8601`, `expected_package_version`, `expected_jurisdiction_rule_version`, `findings`, `corrected_findings`, `finding_ids`, `limit`, `offset`) all present in backticks; 0 missing.
- **Contract 2 (Rule Coverage): PASS** — all 12 state machines' transitions (from/to states, preconditions paired with error IDs, side effects including cascades), all 12 calculations (business_hours_between, sla_due_at walk, strict-greater SLA evaluation, 3-breach probation boundary, business_day_add send-day-exclusion, max(5, jurisdictional) adverse wait, hold-day exclusive/inclusive counting, lookback cutoff strict-before with salary exemption, first-match-wins matrix evaluation with no-match→CLEAR and ADVERSE_ELIGIBLE > IA_REQUIRED > CLEAR precedence, provisional/final fee variants with floor-before-subtract 10% credit and RESCREEN zero-fee, pooled-then-rounded accuracy bps with both variants and 10000 empty-set default, strict >200 bps fail threshold, closed-interval re-screen sweep with delivered_at/created_at ordering, active_order_count invariant), both OCC rules with exact error IDs and 412 status, validation pipeline priority ordering stated explicitly (SoD check pinned before the temporal gate; the §2.8 ten-stage pipeline), all validation `applies_to` scopes enumerated, sibling-branch symmetry preserved (UPHELD/AMENDED/WITHDRAWN resolution paths each fully specified). 59/59 rule spot checks pass; all 44 error IDs appear in §2/§3 prose; all enum values and state names present as exact UPPERCASE strings (including the initially-missed `RESOLVED_UPHELD`/`RESOLVED_AMENDED` terminal states and `report_id`, both repaired).
- **Contract 3 (§3 Path Purity): PASS** — 480 backtick tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combinations. All §3 endpoint references use state-transition framing, role+verb, or capability descriptions.
- **Contract precision spot-checks: PASS** — §2.2 emitted byte-identical to the canonical block (verified `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, and `"data": { }` all intact); pagination defaults (10/1/100/0) and `created_at`-ascending sort stated; all 7 role names spelled exactly with entity-backed vs opaque identity prose for each.

## Step 5: Generate Unit Tests — 2026-08-13T08:41:00.000Z

All 93 tests collect cleanly. The suite is complete and validated. Final summary:

## Summary

Generated the complete test infrastructure and suite for task_1434 (Employment Background Screening Vendor Management).

### test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/test_helpers/`)
- `__init__.py` — barrel export (framework generics + PRD-specific code)
- `types.py` — 7-role `UserRole` enum, 14 entity TypedDicts (all carry the full common-field set per PRD §2.5 "none are exempt"), 15 status/domain enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 40 endpoint methods covering every PRD endpoint (clock, vendors, audits, packages incl. OCC PUT, jurisdiction rules incl. OCC PATCH, matrices, positions, candidates, orders + consents/dispatch/cancel/escalate/assessments/decision, consent revoke, reports + findings, adverse cases, disputes)
- `api_errors.py` — all 45 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_instant_equals` (fractional-digit-tolerant instant comparison), `assert_vendor_capacity_invariant`
- `factories.py` — payload factories with canonical defaults (`ADVERSE_RULES`, `IA_RULES`)
- `constants.py` — FCRA wait 5, breach threshold 3, audit fail 200 bps, SLA credit 10%, consent 90d, dispute 30d, clock default
- `test_users.py` — shared constants for the 5 opaque roles + `make_candidate_headers`/`make_vendor_agent_headers` entity-backed builders (ownership threading)
- `fixtures.py` — tiered composites: `setup_screening_config` → `setup_consented_order` → `setup_dispatched_order` → `setup_report_received` → `setup_pre_adverse_case` → `setup_disputed_order`/`setup_disputed_pre_adverse`, plus audit and read-back helpers

### test_suite/ (11 files, same task directory)
`conftest.py` + 10 numbered test files: `test_01_catalog_and_config.py` (10), `test_02_access_control.py` (3), `test_03_order_opening_and_consent.py` (7), `test_04_dispatch_sla_escalation.py` (12), `test_05_report_delivery_and_outcome.py` (10), `test_06_adjudication_and_adverse_action.py` (10), `test_07_disputes_and_reinvestigation.py` (12), `test_08_cancellation_and_consent.py` (7), `test_09_vendor_accuracy_audits.py` (12), `test_10_platform_invariants.py` (5) — plus conftest = **93 tests total**, collected by pytest with RC 0.

### Per-queue counts
- **Queue A (Difficulty): 19/19 instances emitted, 38 tests (exactly 2 each), 0 skipped**
- **Queue B (Corner): 54/54 non-stub instances emitted, 55 tests (consent-expiry boundary got 2), 0 skipped**
- **4 stubs not translated** (their difficulty cross-references all resolve): `rescreen_order_self_referential_fk` → `rescreen_sweep_closed_interval_inclusion`; `findings_computed_flags_on_subresource` → `adjudication_first_match_rule_ordering`; `dispute_resolve_upheld_happy_path` → `order_parallel_dimensions_dispute_cycle`; `fee_sla_credit_value` → `order_fee_provisional_vs_final_with_sla_credit`

### Notable PRD-first adjudications (no instances skipped; three assertion-level corrections)
- `arrest_records_excluded_by_jurisdiction`: asserted `matched_action == "CLEAR"` (not null) because PRD §3.5 states "A finding that matches no rule defaults its `matched_action` to `CLEAR`, as does any non-considerable finding."
- OCC tests assert `version == captured + 1` rather than literal 2/3, since PRD §2.5 pins "increments by one on every mutation" but never the initial value.
- `rescreen_order_cannot_dispatch_to_audited_vendor`: added a reinstate step so `ERR_RESCREEN_SAME_VENDOR` is isolated from `ERR_VENDOR_NOT_ACTIVE` (PROBATION vendor), per the validation-priority isolation rule.
- `dispute_window_thirty_day_boundary`: reordered arms across two orders so the logical clock only advances monotonically (boundary success first at exactly +30d, then +1s rejection).

### Stage 2 tag validation
93/93 tests carry exactly one `Design:` tag; all tags resolve to real instances; queue A ≥2 per instance and queue B ≥1 per non-stub instance verified programmatically; all 93 docstrings carry a ≥8-word PRD quote surviving normalized literal grep of PRD.md; pyflakes clean (except intentional barrel re-exports); `python3 -m pytest test_suite --collect-only` collects 93 tests with RC 0.

## Step 6: Generate Implementation — 2026-08-13T08:47:00.000Z

The only "seed" matches are docstrings stating there is no seeding. Implementation complete.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/workspace/implementation/`.

**File list**
- `start.sh` — reads `$PORT` (default 10000), binds `0.0.0.0`, guarded `pip install` (no-op once Flask present), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=2.2`
- `app.py` — app factory, blueprint registration, envelope-shaped error handlers (ApiError/404/405/400/500)
- `db.py` — in-memory stores: 14 dicts keyed by id, common-field factory (`id`/`created_at`/`updated_at`/`version` + internal `_seq`), `bump()` for version/updated_at on every mutation
- `errors.py` — ApiError + all 45 catalog error IDs
- `response.py` — exact envelope (`meta.api_request_id` `req_*`, `api_request_timestamp` ISO-8601 millis UTC, `response_type` object/array/error, `data.error_id`/`message`; list meta adds `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 7-role RBAC, shape validators, pagination (limit default 10, min 1, max 100; offset default 0)
- `timeutil.py` — logical clock (default `2026-08-01T00:00:00Z`), business-window hours (Mon–Fri 09:00–17:00Z, Decimal 2dp ROUND_HALF_UP), `sla_due_at` window-walk, `business_day_add` (send day excluded, pinned 00:00:00Z), anniversary-year recency/lookback
- `services.py` — cancel compensation cascade (vendor count −1, fee void, case ABORTED, IA VOID), finding considerability + first-match matrix evaluation, worst-of outcome precedence, pooled accuracy bps (single round-half-up after pooling), case lazy WAITING_PERIOD→ELIGIBLE_FOR_FINAL flip, hold-day accumulation
- `routes/` — 13 modules: clock, vendors, audits (incl. finalize fail threshold >200 bps, probation/decertify cascade, re-screen sweep ordered by delivered_at/created_at), packages (OCC `expected_package_version` 412, retire in-use check), jurisdictions (OCC patch), matrices, positions (credit-check prohibition), candidates (email uniqueness, withdraw cascade), orders (ban-the-box gate, consent capture with EXPIRED recovery, dispatch with capacity/consent-freshness/rescreen-vendor gates, escalate, IA, adjudication decision with SoD case creation), consents (revoke cascade), reports (SLA turnaround/breach, fee finalization with floor-10% credit, RESCREEN zero fee, matrix pinning), cases (send-final-notice SoD-before-temporal, abort), disputes (file/window/already-open, resolve UPHELD hold-extension and AMENDED pinned-matrix re-eval + case abort, withdraw)

**Endpoint coverage: 53/53** — every endpoint in the PRD §4 table / scaffold §1.5 is implemented (1 clock + 4 vendor + 4 audit + 5 package + 4 jurisdiction + 4 matrix + 3 position + 3 candidate + 10 order/consent/IA + 1 consent revoke + 4 report + 4 case + 5 dispute + clock).

**Constraints confirmed**
- In-memory only: all state in `db.py` module-level dicts; no SQLite, no file/JSON persistence, no /tmp cache
- No seed/preload/hardcoded entities at startup — store is empty on every boot (verified: fresh boot returns `total_count: 0` and clock default `2026-08-01T00:00:00.000Z`)
- Never read `test_suite/` or `test_helpers/`
- `start.sh` verified booting via the exact `bash start.sh` contract with `$PORT` set, responding within ~3s

**Validation performed**: six self-written end-to-end suites (primary workflow, audits/re-screen sweep/decertify, consent expiry+capacity+cancel/revoke, considerability/lookback/salary-exemption/IA gates/dispute window/3-breach probation, matrix-gate/OCC-precedence/200-bps pass boundary) — all pass, each against a fresh process boot, including exact assertions on `sla_due_at`, `earliest_final_notice_at` with hold extension, fee math (9000 after 10% credit; 0 for RESCREEN), and pooled accuracy (9333 bps draft-including vs 10000 finalized).

## Step 7: Run Tests and Iterate — 2026-08-13T09:10:00.000Z

All 8 rounds pass 93/93 — clean sweep. The exit condition is met.

## Summary

**Iterations run:** 3 eight-round sweeps (62 → 5 → 0 failing; final sweep: 93/93 passed in every one of the 8 parallel rounds).

**Tests deleted:** none. Every failing test traced to PRD-verbatim rules; no PRD-silence or unique-derivability deletions were needed.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/test_helpers/api_errors.py` — added `ERR_MATRIX_ALREADY_ACTIVE` to `ApiErrorId` and its 409 mapping. PRD §3.1 names it verbatim ("rejects when another matrix is already `ACTIVE` for the same tier (`ERR_MATRIX_ALREADY_ACTIVE`)") and the implementation already emitted it; the helper enum was simply incomplete (caused an `AttributeError`).
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/test_helpers/api_client.py` — `set_clock(to_iso8601, headers=None)` now defaults to HRAdmin headers. Tests drive the clock bare; PRD restricts the endpoint to HRAdmin/ComplianceOfficer, so defaulting to HRAdmin is PRD-consistent (~13 tests failed with `TypeError: missing headers`).
- `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/test_helpers/fixtures.py` — `setup_consented_order` now (a) accepts and ignores a `dispatch_at` kwarg (tests pass `dispatch_at=None` for call-site symmetry; this stage never dispatches), and (b) advances the logical clock to `consent_signed_at` when that instant lies past the startup default. The fixture previously captured consent signed at 2026-08-04 while the fresh-boot clock sat at the 2026-08-01 startup default, violating PRD §3.3's "authorization_signed_at must not lie in the future" — the implementation correctly rejected it (ERR_CONSENT_IN_FUTURE), so this was a fixture precondition bug accounting for ~40 failures. The Saturday-anchor test (consent 2026-07-31, before the default) deliberately leaves the clock untouched.

**Fixes applied to `test_suite/`:**
- `test_03...::test_order_create_missing_candidate_id_returns_invalid_request` — now builds a real position before omitting `candidate_id`. The old payload carried an unresolvable `position_id`; PRD §2.8's pipeline checks existence (3rd) before required-fields shape (5th), so a PRD-faithful server returns ERR_NOT_FOUND, not ERR_INVALID_REQUEST.
- `test_04...::test_delivery_at_exact_due_instant_is_on_time`, `test_04...::test_one_business_hour_late_breaches_and_moves_counter`, `test_05...::test_final_fee_applies_sla_credit_on_late_delivery` — dropped `with_matrix=False` from their setups. PRD §3.1 states report deliveries "fail for lack of an active matrix" unconditionally, so delivering with no ACTIVE matrix is a PRD-inconsistent precondition; the asserted rules (SLA boundary, fee credit) are orthogonal to the matrix.
- `test_07...::test_double_finalize_and_double_open_dispute` — relaxed the exact `ERR_DISPUTE_ALREADY_OPEN` assertion to `validate_error_is_one_of([ERR_DISPUTE_ALREADY_OPEN, ERR_REPORT_NOT_ACTIONABLE, ERR_ORDER_ADJUDICATION_TERMINAL])` (the permitted error-precedence-silence correction). §3.9 names ALREADY_OPEN for a second filing, but an open dispute forces report=DISPUTED and adjudication=DISPUTE_HOLD, so §2.8's pinned pipeline (state preconditions 6th, uniqueness 8th) admits either state error surfacing first; both readings are PRD-faithful.
- `test_09...::test_rescreen_order_cannot_dispatch_to_audited_vendor` — fixed a tuple-indexing typo: `list_orders_filtered` returns `(data, meta)`, and the old line indexed `[0]["id"]` on the tuple (deterministic `TypeError`).

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful in every failure case (including the consent-freshness gate, the active-matrix delivery gate, and the §2.8 validation pipeline order); all 62 initial failures were test-artifact bugs.

## Step 8: Finalize PRD — 2026-08-13T09:25:00.000Z

All three edits are in place; the diff shows exactly the intended changes and nothing else. Final verification complete.

## Summary

**Line counts:** `PRD.md` = 319 lines; `PRD_FINALIZED.md` = 320 lines (+1 line, +0.31%). Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1434_employment_background_screening_vendor/workspace/PRD_FINALIZED.md`

### Changes (one bullet per edit)

- **§5 Error Code Catalogue** — insert — added the missing row `| ERR_MATRIX_ALREADY_ACTIVE | 409 |` between `ERR_MATRIX_NOT_DRAFT` and `ERR_MATRIX_NOT_ACTIVE`, mirroring the `ERR_JURISDICTION_RULE_ALREADY_ACTIVE` sibling placement — `implementation/routes/matrices.py:97` (emits 409), `implementation/errors.py:32`.
- **§3.1 (matrix retirement / delivery gate)** — revise — the clause "future report deliveries for that tier will then fail for lack of an active matrix" now names the concrete rejection: "any report delivery for a position whose risk tier has no `ACTIVE` matrix is rejected with `ERR_MATRIX_NOT_ACTIVE` (HTTP 409)" — `implementation/routes/reports.py:115-121` (gate in `create_report`), `implementation/services.py:31-34` (`active_matrix_for`).
- **§3.9 (dispute filing precedence)** — revise — replaced "a second filing while one is `UNDER_REINVESTIGATION` is rejected with `ERR_DISPUTE_ALREADY_OPEN`" with wording that keeps the uniqueness rule named but pins the observable outcome: the uniqueness check runs after the state preconditions (per §2.8), the report-actionability check runs before the adjudication-state check, and since an open dispute holds the report `DISPUTED` and adjudication `DISPUTE_HOLD`, a second filing surfaces `ERR_REPORT_NOT_ACTIONABLE` — `implementation/routes/disputes.py:56-73` (check order: report → adjudication → uniqueness; the `ERR_DISPUTE_ALREADY_OPEN` raise at line 71 is unreachable).

### Step-7 items requiring NO PRD change (with reasons)

- **`test_helpers/api_errors.py` enum gap** — pure helper bug; PRD §3.1 already names `ERR_MATRIX_ALREADY_ACTIVE` verbatim. (The residual §5 catalogue omission it revealed is closed by Edit 1.)
- **`test_helpers/api_client.py` `set_clock` default headers** — pure test convenience; PRD §2.4 and the §4 table already restrict the endpoint to HRAdmin/ComplianceOfficer; `implementation/routes/clock.py:15` matches.
- **`test_helpers/fixtures.py` consent clock advancement + ignored `dispatch_at` kwarg** — pure fixture precondition bug; PRD §3.3 already pins "authorization_signed_at must not lie in the future" and `implementation/routes/orders.py:173-175` enforces it (`ERR_CONSENT_IN_FUTURE`).
- **`test_03` missing-`candidate_id` fix** — pure test bug; PRD §2.8 already pins existence (3rd) before request shape (5th), and `implementation/routes/orders.py:56-64` implements exactly that (unresolvable `position_id` → `ERR_NOT_FOUND` before the required-field check).
- **`test_09` tuple-indexing typo** — pure test bug (`list_orders_filtered` returns `(data, meta)`); no behavioral content.

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

**Edit 1 (§5 row):**
- (a) Subject: `ERR_MATRIX_ALREADY_ACTIVE` error id and HTTP status.
- (b) Enumerated: `errors.py:32` (constant); grep across all `routes/*.py` — sole emission at `matrices.py:97` (activate, 409); catalogue sibling `ERR_JURISDICTION_RULE_ALREADY_ACTIVE` at 409. No other path emits or consumes this id.
- (c) No wording adjustment needed (bare catalogue row).

**Edit 2 (§3.1 delivery matrix gate):**
- (a) Subject: the requirement that report delivery needs an ACTIVE matrix for the position's risk tier.
- (b) Enumerated: `reports.py:92-177` — the only delivery path (`POST /screening-reports`); gate order is ownership → findings shape → `DISPATCHED` state → active-matrix gate → check_type-in-package referential check. `services.py:31-34` — `active_matrix_for` returns None both when a tier never had a matrix and after retirement (both cases covered). `disputes.py:181-187` — AMENDED resolution re-evaluates against the order's **pinned** matrix with no active-matrix gate (wording scoped to "report deliveries" so this path is untouched; §3.9's pinned-matrix rule stays consistent). `matrices.py:104-114` — retire gate (`ERR_MATRIX_NOT_ACTIVE` for non-ACTIVE retire) unchanged. GET report/findings endpoints need no matrix.
- (c) Widened from the retirement-only framing to "any report delivery for a position whose risk tier has no ACTIVE matrix", because the Step-7 `with_matrix=False` tests exercised the never-created case, which the impl gate also rejects — the original retirement-scoped clause alone would have left that impl behavior unpinned.

**Edit 3 (§3.9 double-dispute precedence):**
- (a) Subject: validation order within dispute filing and the error observed on a second filing while one is open.
- (b) Enumerated: `disputes.py:30-103` — full filing pipeline (existence → ownership → `finding_ids` existence → `reason` shape → report-actionable → adjudication-reviewable → one-open uniqueness → 30-day window). `disputes.py:140-201` and `204-231` — resolve/withdraw emit only `ERR_DISPUTE_NOT_OPEN`; unaffected. Grep for `DISPUTE_HOLD|UNDER_REINVESTIGATION|DISPUTED` outside `disputes.py` → zero hits; `services.py` `cancel_order_cascade` does not touch disputes — so the invariant "open dispute ⇒ report `DISPUTED` ∧ adjudication `DISPUTE_HOLD`" holds in every reachable state, making `ERR_REPORT_NOT_ACTIONABLE` the deterministic outcome of any second filing. Grep confirmed `ERR_REPORT_NOT_ACTIONABLE`/`ERR_ORDER_ADJUDICATION_TERMINAL`/`ERR_DISPUTE_ALREADY_OPEN` are emitted nowhere else, so the wording cannot mis-describe another endpoint.
- (c) Kept `ERR_DISPUTE_ALREADY_OPEN` named as the uniqueness rule's error (the check exists in impl, `disputes.py:71`) instead of deleting it, and explicitly scoped the "report check before adjudication check" ordering to dispute filing rather than claiming a global intra-state-category order — avoiding a false universal claim about other endpoints.

## Step 9: Complete PRD — 2026-08-13T09:55:00.000Z

PRD_COMPLETED.md is complete. Final report:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (320 lines, 52,267 chars) → `PRD_COMPLETED.md` (320 lines, 54,780 chars). Char-delta: **+2,513**. All edits are inline in-paragraph inserts/revisions; no new sections or paragraphs; line count unchanged.

**Counts:** 21 ambiguity-pins, 2 mismatch-revisions (23 changed lines total).

**Changes** (format: section — insert|revise — ambiguity|mismatch — what changed — impl source):

1. §2.3 Pagination — revise — ambiguity — out-of-range `limit`/`offset` clamped into range, non-integer values fall back to defaults; `created_at` ties broken by creation order; `has_more` true exactly when `offset` + returned items < `total_count` — middleware.py:123-142, response.py:43
2. §2.4 Logical clock — revise — ambiguity — clock set unconditionally (may move backward); returns 200 with `data.current_utc` echoing new time — routes/clock.py:12-23
3. §2.5 Common properties — revise — ambiguity — `version` starts at 1 at creation — db.py:41
4. §2.6 Monetary — revise — ambiguity — turnaround times serialized as JSON numbers — response.py:26-27
5. §2.8 Validation pipeline — insert — ambiguity — malformed/absent JSON body treated as empty object; non-object JSON body is itself a shape error — middleware.py:45-52
6. §3.1 Vendor registration — revise — ambiguity — `base_tat_business_hours` and `surcharge_cents` accept any integer, no minimum enforced — routes/vendors.py:23-27
7. §3.1 Package update — insert — ambiguity — update applies only fields present in body; omitted fields unchanged — routes/packages.py:96-103
8. §3.1 Rule patch — revise — ambiguity — patch may revise any field except `jurisdiction_code`; partial-field semantics — routes/jurisdictions.py:82-104
9. §3.1 Matrix rules — revise — ambiguity — `max_recency_years` is a non-negative integer — routes/matrices.py:41
10. §3.2 Order opening — insert — **mismatch** — pinned creation gate order: id existence (candidate then position) → ban-the-box → duplicate-order uniqueness → candidate-ACTIVE (PRD narrative implied candidate-ACTIVE first) — routes/orders.py:55-93
11. §3.4 Dispatch — insert — **mismatch** — pinned dispatch gate order: CONSENT_CAPTURED → rescreen same-vendor → consent freshness → package-ACTIVE → vendor capacity → vendor-ACTIVE (PRD narrative described vendor-ACTIVE/capacity before package/consent) — routes/orders.py:216-250
12. §3.4 Escalation — insert — ambiguity — non-DISPATCHED order rejected with `ERR_ORDER_NOT_DISPATCHED`, checked before the temporal gate — routes/orders.py:286-291
13. §3.5 Report delivery — revise — ambiguity — `findings` array may be empty — routes/reports.py:108-110
14. §3.5 Fees — revise — ambiguity — `provisional_fee_cents` persists on the order after delivery alongside `final_fee_cents` — routes/reports.py:158-165
15. §3.5 Considerability — revise — ambiguity — lookback anniversary subtraction clamps Feb 29 to Feb 28 — timeutil.py:133-138
16. §3.6 Adjudication decision — insert — ambiguity — response carries the updated order for either decision (not the created case) — routes/orders.py:354-358,397
17. §3.7 Case abort — revise — ambiguity — aborting a case clears `hold_started_at` to null (also applies to cascade aborts) — routes/cases.py:94-95, services.py:101
18. §3.9 Dispute filing — revise — ambiguity — each `finding_ids` entry must reference an existing finding, checked left-to-right (`ERR_NOT_FOUND`), but membership in the order's own report is not verified; absent list stored as null — routes/disputes.py:44-51,83
19. §3.9 Dispute creation — revise — ambiguity — fresh dispute has `resolved_at`/`outcome` null and `overdue` false — routes/disputes.py:79-89
20. §3.9 AMENDED resolution — revise — ambiguity — corrected findings validated for shape only (no pinned-package `check_type` re-check); re-evaluation uses the report's original `delivered_at` as delivery date — routes/disputes.py:155-186
21. §3.9 Dispute outcome — revise — ambiguity — a withdrawn dispute's `outcome` stays null — routes/disputes.py:227-229
22. §3.10 Vendor reinstatement — revise — ambiguity — reinstatement does not reset `consecutive_sla_breaches` — routes/vendors.py:70-80
23. §3.11 Re-screen sweep — revise — ambiguity — rescreen order also copies `conditional_offer_extended_at`; all dispatch/fee/pinning fields null, `escalation_level` zero — routes/audits.py:146-167

**Verification approach:** all 45 endpoints, both state-machine dimensions, all cascades (cancel/revoke/withdraw/decertify), fee/SLA/accuracy/hold arithmetic, error ordering per endpoint, and response shapes were walked against the PRD. Behaviors already uniquely pinned by PRD_FINALIZED (envelope format, role table, OCC semantics, SLA walk, fee floor, accuracy pooling, sweep selection, dispute-window boundaries, SoD-before-time ordering, second-dispute `ERR_REPORT_NOT_ACTIONABLE` path, etc.) were left untouched. Flask-infrastructure edges (405 handler, trailing-slash tolerance) were judged out of PRD scope and not pinned.

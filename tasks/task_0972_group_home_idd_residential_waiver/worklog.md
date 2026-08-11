# Worklog — task_0972_group_home_idd_residential_waiver

Scenario (verbatim): generate task hard than expert level! 972. Group Home & IDD Residential (waiver): individual & person-centered plan (ISP), bed/house & DSP staffing ratio, waiver service authorization & units, med & behavior-support plan, incident/EVV & compliance, day-program transport, billing, review

## Step 1: Create Task Directory — 2026-08-10T06:39:14.469Z

Pre-assigned output folder `tasks/task_0972_group_home_idd_residential_waiver` with `workspace/` subdirectory already existed per command args; auto-index scan skipped as instructed. Verified directory structure on disk. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T07:32:10.760Z

Scaffold generation complete for task 0972 (Group Home & IDD Residential Waiver), harder-than-expert difficulty. All artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/`.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1063 calls scanned across both design files.)

**§1.1–§1.7 counts (SCAFFOLD.yaml):** 15 entities, 13 state machines, 9 calculations, 34 validation rules (priority-ordered, safety → temporal → referential → constraint → fiscal), 87 endpoints, 33 error codes, 7 roles (6 operational + `Any`), 2 OCC concurrency rules.

**§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml):** 22 instances across all 9 difficulty rules — dual_variant_calc 3, combinatorial_formula 3 (modes a/b/c all covered), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2. All numeric asserts precomputed and verified by executing the formulas (e.g., 100 min → 7 provisional vs 75/15 = 5 final units; two 8-min visits → 2 units/3000 cents per-visit-first vs 1 unit sum-then-round; recoupment min(floor(30000×0.10), 30000) = 3000 → net 27000).

**§1.9 (SCAFFOLD_CORNER_DESIGN.yaml):** all 9 taxonomy sections, 65 entries = 58 full test recipes + 7 `excluded_because` stubs pointing at §1.8 instances.

**Key design decisions for downstream steps:**
- **Flat topology, `api_prefix: /`** — all resources top-level (`/isps`, `/evv-visits`, ...) with FK links in bodies; every entity has a single-GET (required for the lint's FK segment derivation) and FK-filtered list GETs.
- **Logical clock:** `POST /_clock/set_current_utc` with pinned startup default `2026-05-01T00:00:00Z`; drives ISP/auth/BSP expiry and trip completion.
- **Signature mechanics:** (1) unit waterfall allocation across successor authorizations with LIFO release on claim void; (2) two-axis EVVVisit (verification_status × billing_status); (3) incident→home-posture→claim-HOLD→agency-held-count depth-3 cascade with symmetric release on close; (4) ISP expiry → auth SUSPEND → visit REJECT depth-3 cascade; (5) pinned recoupment evaluation order (gross → recoup vs pre-payment balance → net); (6) three distinct interval semantics: bed half-open adjacency, vehicle half-open per (vehicle,date), shift 8-hour rest buffer (inclusive at exactly 8h).
- **Segregation of duties is non-vacuous by construction:** ISP/BSP authoring is shared CaseManager|QIDP and incident submit shared DSP|QIDP, so same-person approve/close is reachable and rejected (`ERR_SEGREGATION_OF_DUTIES`); claim submit/pay separation uses opaque billing user ids (`bill-1`/`bill-2`).
- **Two OCC true-races only:** ISP create-with-supersede on `Individual.version` and ISP amend-supersedes-amendment on `ISP.version` (both 412 `ERR_STALE_VERSION`); all other write conflicts are state preconditions per §1.2.1's filter.
- MedAdminEvent is intentionally immutable (`common_fields: false`, append-only MAR). A `workspace/` dir and `worklog.md` pre-existed in the task directory and were left untouched.

(Note: first Step 2 subagent exited prematurely without writing files; re-spawned and completed successfully. Orchestrator verified all three files on disk and parse as valid YAML: SCAFFOLD.yaml 1547 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 980 lines, SCAFFOLD_CORNER_DESIGN.yaml 1502 lines.)

## Step 3: Copy Shared Files — 2026-08-10T07:32:36.841Z

Copied `./INSTRUCTION.md` to `tasks/task_0972_group_home_idd_residential_waiver/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T07:39:02.715Z

The PRD is complete. Final summary:

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/workspace/PRD.md`
**Line count**: 370 lines
**Sections** (5 top-level, 12 in §2, 10 in §3):

- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Optimistic Concurrency Control
  - 2.6 Validation Ordering
  - 2.7 Precision and Rounding
  - 2.8 Nested Resource Retrieval and Path Validation
  - 2.9 The Logical Clock
  - 2.10 Hierarchical Consistency and Cascading Side Effects
  - 2.11 The Compliance-Posture Gate
- §3 Business Logic & Workflows
  - 3.1 Agency Bootstrap, Homes, and the Logical Clock
  - 3.2 Individuals, Enrollment, and Discharge
  - 3.3 Individual Service Plans and Service Authorizations
  - 3.4 Staff, Shifts, and Weighted Staffing Compliance
  - 3.5 Bed Assignments and the Admission Gate
  - 3.6 Medication Orders and Medication Administration Records
  - 3.7 Behavior Support Plans and Incident Reporting
  - 3.8 EVV Visits, Waterfall Allocation, and the Consumption Ledger
  - 3.9 Day-Program Transport and Vehicle Capacity
  - 3.10 Billing Claims, Recoupment Netting, and Void Compensation
- §4 Endpoint Definitions (84-row table, 4 columns: Method / Path / Description / Authorized Roles)
- §5 Error Code Catalogue (33 rows, 2 columns: Error ID / HTTP Status)

**Coverage notes** (scaffold → PRD mapping):

- `entities[]` (15 entities, 101 fields) → all fields distributed across §2.4 (common properties) and §3 narrative; `MedAdminEvent`'s common_fields=false called out explicitly
- `state_machines[]` (13 machines) → §3 workflow narratives; cyclic ISP/BSP paths and parallel-dimension EVVVisit verification×billing captured
- `calculations[]` (8 rules) → §3.4 (weighted staffing, census variants), §3.6 (med adherence), §3.7 (incident deadline, home posture), §3.8 (billable unit, waterfall), §3.10 (claim aggregation, recoupment netting); constants embedded in prose (e.g., "ten percent", "fourteen days", "360 minutes", "5000000 cents")
- `validations[]` (29 rules) → §2.6 priority ordering, plus each rule's trigger condition paired with its error_id inline in §2/§3
- `concurrency_rules[]` (2 OCC rules) → §2.5 with `expected_individual_version` / `expected_isp_version` + `ERR_STALE_VERSION` + 412
- `endpoints[]` (84 endpoints) → §4 minimal table + §3 narratives
- `errors[]` (33 codes) → §5 two-column table; every error also referenced in §2/§3 prose
- `roles[]` (7 roles) → §2.1 with exact spelling + identity prose for entity-backed (CaseManager/QIDP/DSP) and opaque (AgencyAdmin/BillingSpecialist/ComplianceOfficer/Any) roles

**Hard contracts**:
- Contract 1 (Field-Name Coverage): 101/101 entity fields, 90/90 endpoint inputs, 15/15 path params — PASS
- Contract 2 (Rule Coverage): 24/24 spot checks across all six high-risk categories (validation priority, OCC, cross-entity side effects, applies_to scopes, structured field content, sibling-branch symmetry) — PASS
- Contract 3 (§3 Path Purity): 791 backtick tokens scanned, 0 path-like, 0 bare HTTP methods, 0 method+path — PASS

(Orchestrator verified PRD.md on disk: 370 lines, 59573 bytes.)

## Step 5: Generate Unit Tests — 2026-08-10T08:02:14.241Z

All test infrastructure and test cases were generated for `task_0972_group_home_idd_residential_waiver` and verified on disk.

### Counts
- **Queue A (Difficulty)**: 45 tests across all **22/22 instances** — every instance has ≥ 2 tests.
- **Queue B (Corner)**: 106 tests across all **58/58 non-stub instances** — every instance has ≥ 1 test. The 7 `excluded_because:` stubs (all in the `errors` section) were **not translated**; their cross-references all resolve to real difficulty instances.
- **Total**: 151 test functions, each with exactly one terminal `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` docstring line resolving to a real instance, and a verbatim PRD citation (all 144 quoted citations survive literal grep of PRD.md).

### Per-instance skip list
None. Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. No `skip` / `skipif` / `xfail` markers exist anywhere in the suite.

### File inventory written
`test_helpers/` (9 files, all compile):
- `__init__.py` (barrel: framework generics re-exported + PRD-specific)
- `types.py` (status enums, role enum, 16 entity TypedDicts; `MedAdminEvent` correctly omits `updated_at`/`version` per the append-only exception)
- `api_client.py` (`ApiClient(GenericApiClient)` with one method per PRD endpoint; module-level `api_client`)
- `api_errors.py` (33 `ApiErrorId` values + HTTP map, registered via `set_error_http_status_map`)
- `assertions.py` (per-entity shape assertions)
- `factories.py` (payload factories, input fields only, unique-suffix generator for `medicaid_id`/`license_number`)
- `constants.py` (domain thresholds: ratios, 15-min unit, 360-min DAY threshold, 24/48/72h windows, 30d adherence window, 8-slot vehicle cap, 5M/20M fiscal caps, 180/365d BSP review)
- `test_users.py` (`TEST_USERS` shared constants + per-instance `make_*_headers` builders for the three entity-backed roles)
- `fixtures.py` (composite tiers: agency/staff/individual setup, ISP walk to ACTIVE, authorization walk to ACTIVE, resident admission, `setup_billable_pipeline`, verified-visit and claim helpers)

`test_suite/` (12 files, all compile):
- `conftest.py` (session `api` fixture + per-role header fixtures)
- `test_01_computed_reads_and_units.py` (dual-variant census/EVV-units/staffing, weighted ceiling, per-visit rounding)
- `test_02_billing_and_ledgers.py` (recoupment netting order, pay/void cash conservation, LIFO unit release, correct-resubmit cycle, overpayment boundary, claim guards, sweep input set)
- `test_03_isp_lifecycle_and_occ.py` (amendment cycle, return loop, invalid approve, EXPIRED lockdown, both OCC rules)
- `test_04_cascades.py` (critical-incident 3-link cascade, ISP-expiry cascade, discharge fan-out, close-release, PROVISIONAL no-hold)
- `test_05_homes_beds_and_shifts.py` (capacity exact-fill, half-open bed adjacency, 8h rest buffer, suspend cascade, close gate, occupancy reconciliation, move-in gate, shift confirm/complete, cancelled-shift exclusion)
- `test_06_medications_and_behavior_plans.py` (discontinued-order gate, MAR immutability, ±60-min window, witness rules, adherence windows/null, enrollment gate, BSP level mismatch, BSP supersede/review-due)
- `test_07_incidents.py` (strict-greater deadline, severity windows, resubmit lateness recompute, CLOSED lockdown)
- `test_08_evv_and_authorization_gates.py` (exhaustion at equality, waterfall all-or-nothing, authorization-active gate, span containment, geo exception, DAY 360 threshold, parallel dimensions, ISP-active gate, fiscal caps, priority pairs)
- `test_09_transport.py` (vehicle overlap adjacency, wheelchair slot capacity, DAY_PROG leg gate, clock auto-complete)
- `test_10_rbac_and_identity.py` (missing headers, identity mismatch, terminated-staff identity + shift cascade, role denials, Any-role GETs, claim-submit posture gate)
- `test_11_entities_and_envelope.py` (agency defaults, server-minted fields, missing-name, unknown-field, retrieval, 404, enum rejection, pagination envelope, action-endpoint envelope, immediate consistency)

### Verification performed
- `py_compile` passes on all 21 files.
- Tag audit: 151 tags, 0 bad/duplicate/stub-pointing, 0 missing coverage, 0 stubs emitted.
- PRD citation audit: all quoted rule sentences grep-verbatim against `workspace/PRD.md` (em-dash punctuation matched to the PRD source).
- No scaffold/section references in generated code comments or docstrings.

(Orchestrator verified on disk: test_helpers/ 9 files, test_suite/ 12 files, 151 test functions.)

## Step 6: Generate Implementation — 2026-08-10T08:02:14.241Z

Implementation complete and smoke-tested. Summary:

## File inventory
`/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/workspace/implementation/`
- **start.sh** (executable) — guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` in the foreground
- **requirements.txt** — `flask>=3.0,<4`
- **app.py** (~1,700 lines) — entire implementation: in-memory store, logical clock, envelope, auth, all routes, calculations, cascades

## Endpoints: 87 routes implemented (full endpoint table)
Agencies (2), logical clock (1), homes (8 incl. census + staffing-check computed reads), individuals (5), ISPs (8), authorizations (6), staff (4), shifts (5), bed-assignments (6), medication-orders (4), admin-events (3), med-adherence (1), behavior-plans (7), incidents (8), evv-visits (7), transport-trips (4), claims (8).

## Key behaviors encoded
- **Envelope**: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields `limit/offset/total_count/has_more` in meta for lists (defaults 10/0, max 100, sort `created_at` ASC with insertion-order tie-break); error envelope `data{error_id, message}`
- **Auth**: `X-User-ID`/`X-User-Role` presence (400) → RBAC (403) → entity-backed identity for CaseManager/QIDP/DSP resolving to ACTIVE StaffMember with matching `staff_role` (403 `ERR_ROLE_IDENTITY_MISMATCH`)
- **Logical clock**: boots at exactly `2026-05-01T00:00:00Z`; `POST /_clock/set_current_utc` fires ISP expiry (with 2-link cascade suspending auths and rejecting PENDING/EXCEPTION visits), auth activation/expiration, BSP expiry (strictly past `review_due_at`), trip completion
- **OCC**: `expected_individual_version` on POST /isps, `expected_isp_version` on amend (412 `ERR_STALE_VERSION`), checked before business logic
- **Calculations**: weighted staffing (wheelchair=2, ceiling division, scheduled vs verified-actual variants), census current/projected (+14d), per-visit round-half-up units (never sum-then-round), waterfall allocation with span_start/created_at ordering and atomic full-placement (409 on partial), claim lines grouped by allocated authorization, recoupment netting in pinned order (`recoup=min(floor(gross/10), balance_pre)`), incident deadlines (24/48/72h, strictly-greater lateness), 30-day closed-window adherence floor
- **Cascades**: discharge, home suspend (PENDING beds only), ISP supersede at create and activation, BSP supersede + 180/365-day review due, incident CRITICAL → posture → DRAFT claims → HOLD → `held_claims_count`, close → release HOLD → DRAFT, void → cash reversal + recoupment balance + LIFO unit release + EXHAUSTED→ACTIVE
- **Validation ordering** follows PRD §2.6 priority (auth → RBAC → identity → existence → OCC → state → domain-state → safety → temporal → referential → constraint → fiscal → shape; unit cap before individual cap; claim-period validity before sweep emptiness)
- **No seeding** — store starts empty; computed-field recomputes (occupancy, posture, held count, agency ledgers) mutate the field without bumping the parent's version, matching the scaffold's explicit "increments version" annotations

## Smoke-test result
Server booted via `bash start.sh` on `$PORT` (bound 0.0.0.0, foreground), responded 200 within 3s. Verified end-to-end: agency/home/staff/individual bootstrap, auth failures (400 no-headers, 403 wrong-role, 403 identity mismatch), enroll, ISP OCC create + submit/approve/activate, authorization approve (immediate ACTIVE in-span), bed move-in, EVV create (60min → 4 provisional units), verify with waterfall debit, claim sweep/submit, SoD rejection on payment, full payment, void compensation (cash −4000, recoupment +4000, units released), clock advance → ISP EXPIRED, CRITICAL incident → posture CRITICAL → claim HOLD + `held_claims_count=1` + `ERR_HOME_POSTURE_CRITICAL` gate, close → HOLD release, second full payment netted 3600 against the 4000 recoupment balance, pagination meta. Fresh reboot confirmed empty store (`total_count: 0`, 404 on prior ids). Both smoke servers killed; no leftover processes for this workspace.

(Orchestrator verified on disk: implementation/ contains start.sh (executable), requirements.txt, app.py (92263 bytes). Steps 5 and 6 were launched concurrently in a single assistant message per pipeline spec.)

## Step 7: Run Tests and Iterate — 2026-08-10T08:21:11.377Z

All 8 rounds of the parallel sweep pass: **151/151 in every round, 0 failures** (rounds perfectly consistent in both sweeps — no flakiness observed).

## Summary

**Iterations run:** 2 sweeps (round 1: 132/151 with 19 unique failures, identical across all 8 rounds; round 2 after fixes: 151/151 × 8).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule; all fixes were consistency corrections.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/test_helpers/fixtures.py` — `setup_billable_pipeline` now routes `plan_year_start`/`plan_year_end` overrides to `create_active_isp` instead of leaking them into the authorization payload (they are ISP fields; the leak caused `ERR_INVALID_REQUEST` unknown-field rejections in 3 tests across test_04 and test_08).
- `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/test_helpers/assertions.py` — added `assert_same_instant(actual, expected_iso, label)`: compares ISO 8601 timestamps by instant rather than lexical form. PRD pins the three-fractional-digit format only for `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2); the lexical form of computed timestamps (`report_due_at`, `review_due_at`, `window_start`, `submitted_at`) is not PRD-specified, so exact-string equality was not uniquely derivable. The instant arithmetic itself (the PRD-covered rule) is still asserted exactly.

**Fixes applied to `test_suite/`:**
- `test_04_cascades.py`, `test_06_medications_and_behavior_plans.py` (3 sites), `test_07_incidents.py` (4 sites), `test_11_entities_and_envelope.py` (1 site) — 9 exact-string timestamp assertions switched to `assert_same_instant` (per the partial-coverage rule: kept the covered instant-arithmetic assertion, dropped the uncovered lexical-form assertion).
- `test_02_billing_and_ledgers.py` `TestVerifyThenVoidRestoresUnitPool._setup_two_authorization_paid_claim` — setup created a 4th EVV visit *after* verifying three visits drove A1 to EXHAUSTED; PRD 3.8 requires the referenced authorization to be ACTIVE at creation, so the PRD-faithful implementation correctly rejected the setup. All four visits are now created up front, then verified; the pipeline's incidental default authorization now uses `service_code="RES_HAB"` so the DAY_PROG waterfall involves exactly A1→A2 as the test's design intended.
- `test_08_evv_and_authorization_gates.py` `TestWaterfallFailureRejectsEntireVerify._setup_exhausted_pool_with_pending_visit` — same setup-ordering bug; v4 is now created while the authorization is still ACTIVE, then the pool is exhausted by verifying the first three visits.
- `test_11_entities_and_envelope.py` — added the missing `make_qidp_headers` import (NameError in `test_enroll_response_envelope_and_mutated_fields`).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/workspace/implementation/app.py` — `new_id()` now returns `str(uuid.uuid4())` (canonical dashed form) instead of `uuid4().hex`. PRD 2.4: "The `id` is a server-minted UUID with no type prefix" — the canonical UUID string representation is the dashed 8-4-4-4-12 form; 2 tests (`test_id_and_timestamps_are_server_minted`, `test_admin_event_carries_no_version_or_updated_at`) asserted this via `is_valid_uuid`.

(Orchestrator verified all 8 results files on disk: 151 passed / 0 failed / 151 total / 0 errors in every round.)

## Step 8: Finalize PRD — 2026-08-10T08:29:25.734Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 370 lines, PRD_FINALIZED.md = 370 lines, 0% line delta. Exactly one paragraph (§2.4, first paragraph) differs; ~110 words added inline. No new sections.

### Changes (2, both in §2.4)

- **§2.4 — revise — entity `id` sentence.** "server-minted UUID with no type prefix" now pins "serialized in the canonical dashed 8-4-4-4-12 hexadecimal form". Traces to the step_7 impl fix `new_id()` → `str(uuid.uuid4())`; the original `uuid4().hex` choice proved PRD's wording was non-unique (the runner's `is_valid_uuid` regex requires dashes). — `implementation/app.py:324-326`
- **§2.4 — insert — server-written timestamp format sentence.** Pins that every other timestamp the server writes into a response (`enrolled_at`, `activated_at`, `approved_at`, `submitted_at`, `report_due_at`, `review_due_at`, med-adherence `window_start`/`window_end`, clock `current_utc`) is rendered in the same ISO 8601 UTC format with exactly three fractional digits and a `Z` suffix as `created_at`/`updated_at`. Traces to the `assert_same_instant` helper addition and the 9 relaxed exact-string assertions in test_04/06/07/11 — the impl funnels every server-written datetime through `fmt_dt` (3-digit millis + `Z`). — `implementation/app.py:51-57, 588, 839, 1013, 1667-1668, 1758, 1790, 1896, 1899, 1962, 2414`

### step_7_diff items that produced NO edit (with reason)

- `fixtures.py` plan_year routing — pure fixture bug; unknown-field rejection (`ERR_INVALID_REQUEST`) is already determined by §2.6 input-shape checks + the §5 catalogue (`no_unknown` → `bad()` at `app.py:179-182`).
- test_02 / test_08 setup reorderings — test-design bugs; PRD §3.8 already pins "authorization must be `ACTIVE` (otherwise `ERR_AUTHORIZATION_NOT_ACTIVE`)", which covers creating a visit against an EXHAUSTED authorization. The `RES_HAB` default is fixture design.
- test_11 `make_qidp_headers` import — pure test NameError.

### Per-edit pre-edit search log

**Edit 1 (UUID dashed form):**
- (a) Subject: serialization format of the entity `id` field.
- (b) Enumerated paths: `new_id()` def (`app.py:324-326`); `base_entity()` used by all standard entity creates (`app.py:334-336`); MedAdminEvent create using `new_id()` directly (`app.py:1610`); `api_request_id` mint (`app.py:112`, `req_`+hex — §2.2-governed, not an entity id); FK fields (`individual_id`, `billed_claim_id`, etc.) copy entity-id strings verbatim; test-side `is_valid_uuid` regex (`…/prd_bench_local_runner/testing/assertions.py:19-21`, dashed-only).
- (c) Wording adjustment: kept the sentence's scope strictly on the entity `id` so the `api_request_id` (`req_` prefix rule) and `error_id` paths are untouched; added an example to make "canonical dashed" unambiguous.

**Edit 2 (server-written timestamp format):**
- (a) Subject: lexical format of server-stamped/server-computed timestamps (the fields step_7 relaxed: `report_due_at`, `review_due_at`, `window_start`, `submitted_at`).
- (b) Enumerated paths (complete sweep of `now_iso()`/`fmt_dt(` call sites): envelope `api_request_timestamp` (`:113`), base-entity timestamps (`:335, :341`), MedAdminEvent `created_at` (`:1611`), clock `current_utc` (`:588`), `enrolled_at` (`:839`), ISP `activated_at` (`:1013`), BSP `approved_at` (`:1758`) / `review_due_at` (`:1790`), incident `submitted_at` (`:1896, :1962`) / `report_due_at` (`:1899`), med-adherence `window_start`/`window_end` (`:1667-1668`), claim `submitted_at` (`:2414`) — all funnel through `fmt_dt` (`:51-53`, exactly 3 fractional digits + `Z`). Also checked client-supplied datetimes (`v_datetime` → `fmt_dt`, `:231`, used at 12 call sites incl. `occurred_at`, `check_in_at`, trip legs) — normalized identically, so even a broad reading of "server writes into a response" is consistent; and the internal `strftime` uses (`:746, :854, :1472`) which emit only `YYYY-MM-DD` date strings, never timestamps.
- (c) Wording adjustment: scoped the universal claim to timestamps "the server writes into a response" with an explicit example list mirroring the step_7_diff field names, and said "exactly three fractional digits and a `Z` suffix" to match `fmt_dt` precisely (the `Z` matches the existing §2.2 example `2025-05-24T10:30:00.123Z`).

(Orchestrator verified PRD_FINALIZED.md on disk: 370 lines, 60171 bytes.)

## Step 9: Complete PRD — 2026-08-10T08:37:07.101Z

**Source vs output:** `PRD_FINALIZED.md` (370 lines / 60,171 chars) → `PRD_COMPLETED.md` (373 lines / 64,652 chars), delta +3 lines / +4,481 chars. File written to `/home/ubuntu/github/CodingPRD/tasks/task_0972_group_home_idd_residential_waiver/workspace/PRD_COMPLETED.md`.

**Counts:** 13 ambiguity-pins, 2 mismatch-revisions (15 edited passages total).

**Changes (each inline, no new sections):**

- §2.1 — insert — ambiguity — unrecognized role name in `X-User-Role` rejects with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) — app.py:303-304
- §2.1 — revise — ambiguity — entity-backed identity failure now explicitly covers a non-resolving `X-User-ID` (never `ERR_NOT_FOUND`), all such failures → `ERR_ROLE_IDENTITY_MISMATCH` — app.py:308-313
- §2.2 — insert — ambiguity — unexpected server failure returns `ERR_INTERNAL` (500) in the standard error envelope — app.py:155-162
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties break by creation order; `has_more` = `offset + limit < total_count`; full per-endpoint filter-field enumeration with exact-match semantics; unknown query params ignored — app.py:247-286
- §2.4 — revise — ambiguity — `version` starts at exactly 1 (was "server-defined initial value") — app.py:336
- §2.6 — insert — ambiguity — step 6 generic state check now named as `ERR_INVALID_STATE` (409) — app.py:649-650 and 39 raise sites
- §2.8 — insert — ambiguity — undefined paths/unsupported methods answer `ERR_NOT_FOUND` (404) in the error envelope — app.py:135-152
- §3.3 — insert — ambiguity — ISP amend: replacement `goals_summary` re-validated ≥10 chars; replacement `plan_year_end` must be strictly after `plan_year_start` — app.py:1035-1041
- §3.3 — insert — ambiguity — authorization create: `isp_id` must belong to the stated `individual_id`, else `ERR_INVALID_REQUEST` — app.py:1094-1095
- §3.4 — revise — ambiguity — census read echoes `as_of_date`; staffing-check echoes `shift_date`/`shift_type`; both reads' query params are required with `ERR_INVALID_REQUEST` on missing/malformed; "shift on `shift_date`" pinned as `window_start` calendar-date equality; weighted census uses the half-open convention — app.py:695-777
- §3.5 — revise — mismatch — admission-gate enumeration order corrected to §2.6/impl order (individual-enrolled checked before home-active) — app.py:1392-1395
- §3.6 — insert — ambiguity — discontinuing a non-`ACTIVE` med order rejects `ERR_MED_ORDER_DISCONTINUED` (409); med-adherence `as_of` required — app.py:1565-1566, 1646-1652
- §3.7 — insert+revise — ambiguity (borderline mismatch) — hold cascade fires whenever post-submit recomputed posture is `CRITICAL` (not only on transition into it); release fires whenever post-close posture is below `CRITICAL`; resubmission fires no posture recompute or cascade; `held_claims_count` recomputed for the home's agency and each affected individual's agency — app.py:1807-1834, 1916-1921, 1951-1966, 1981-1985
- §3.8 — insert — ambiguity — EVV create: shift owned by another staff member → `ERR_INVALID_REQUEST` (400); waterfall rejection commits nothing and leaves the visit in its prior `verification_status` (with the pre-assignment `final_units` remaining recorded) — app.py:2031-2032, 2089-2090, 2126-2127
- §3.9 — revise — ambiguity — leg `pickup_at`/`dropoff_at` window is closed: equality with `depart_at`/`return_at` permitted — app.py:2240-2241
- §3.10 — insert — ambiguity — claim lines carry `authorization_id`, `service_code`, `units`, `rate_cents`, `amount_cents` in order of first appearance across the sorted sweep; submit of a line-less claim → `ERR_INVALID_STATE`; posture gate blocks if any active-residency home is `CRITICAL`; `paid_amount_cents` must be a non-negative integer; `lines_override` may cover a subset of lines; void clears each visit's `allocated_units_entries` to empty — app.py:2331-2352, 2404-2413, 2430-2432, 2485-2524, 2554-2563
- §5 — revise — mismatch — catalogue intro scoped to 4xx ids plus the `ERR_INTERNAL` (500) fallback note — app.py:155-162

Everything else in the impl (state machines, caps, waterfall ordering, recoupment netting, rounding rules, cascade membership, OCC guards, role matrix) was already uniquely pinned by PRD_FINALIZED.md and left untouched.

(Orchestrator verified PRD_COMPLETED.md on disk: 373 lines, 64652 bytes.)

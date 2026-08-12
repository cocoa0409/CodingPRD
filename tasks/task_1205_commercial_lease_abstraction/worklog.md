# Worklog — task_1205_commercial_lease_abstraction

## Step 1: Create task directory — 2026-08-11T20:04:00.000Z

Pre-assigned output folder `tasks/task_1205_commercial_lease_abstraction/` with `workspace/` subdirectory already existed; Step 1 treated as done per pipeline invocation. No auto-index scan performed.

## Step 2: Generate scaffold — 2026-08-11T20:32:00.000Z

All three files exist, lint is clean. Here is the verbatim summary:

## Files generated (sizes verified)

- `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/SCAFFOLD.yaml` — 87,561 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 75,755 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/SCAFFOLD_CORNER_DESIGN.yaml` — 105,511 bytes

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  613

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## §1.0–§1.7 SCAFFOLD.yaml summary

**Complexity profile**: primary `ledger_reconciliation` + secondary `temporal_windowing`; layers: optimistic_concurrency, dual_variant_calculation, derived_field_reconciliation, cascading_side_effects; hierarchical topology; **parallel** state machine shape (Lease carries status × abstraction_status × billing_posture); segregation_of_duties role model.

**Entities (12)**: Property, Lease (with parallel dimensions and cached_* derived fields), RentScheduleLine, EscalationStep, RecoveryPool (budget vs actuals + gross-up floor), RecoveryBilling (estimate vs final variant fields), Reconciliation (posted_by vs approved_by for SoD), CriticalDate (polymorphic kinds), ComplianceDoc, Amendment (6 kinds incl. EXTENSION/EXPANSION/CONTRACTION/ASSIGNMENT/RENT_CHANGE/USE_CHANGE), TenantChallenge (cyclic with round_index), AuditRight.

**State machines (9)**: Lease (parallel: lifecycle + abstraction + posture), RecoveryBilling (DRAFT→ISSUED→PAID/DISPUTED/VOID with dispute re-entry), Reconciliation (OPEN→POSTED→APPROVED→CLOSED with CHALLENGED branch), CriticalDate (PENDING/NOTIFIED→EXERCISED/LAPSED/WAIVED), ComplianceDoc (SUBMITTED→UNDER_REVIEW→ACCEPTED/REJECTED/EXPIRED), Amendment (PROPOSED→APPROVED→APPLIED/REJECTED with OCC), TenantChallenge (cyclic OPEN↔UNDER_REVIEW up to 3 rounds + ESCALATED), AuditRight (INVOKED→FIELDWORK→FINDINGS_ISSUED→SETTLED with TIME_BARRED auto-transition).

**Calculations (7)**: `recovery_billing_estimate` (forward-looking, variant=estimate), `reconciliation_final` (waterfall_allocation with gross-up + rounding-remainder absorption in row 12, variant=final), `escalated_rent_for_period` (chronological with pinned per-line rounding), `annual_rent_total` (aggregation, cash basis), `straight_line_rent` (forward-looking GAAP smoothing variant), `audit_window_close` (chronological + 365 days), `occupancy_rate` (aggregation with ACTIVE-status filter).

**Validations (14 priorities)**: auth (401/403), existence (404), invalid_request (400), date_range (422), state (409), segregation_of_duties (409), referential_integrity (422), schedule_overlap (409), coverage_overlap (409), property_overcommitted (409), fiscal gates (409), temporal windows (409), OCC stale_version (412).

**Endpoints (80)**: full CRUD + action endpoints across all 12 entities, plus `POST /lease-admin/_clock/set_current_utc` (default 2026-05-01T00:00:00Z), computed reads (rent-roll with cash|straight_line basis, occupancy-report), and 10 filtered-list GETs for FK reverse-reachability.

**Error catalog (33 codes)**: ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_SEGREGATION_OF_DUTIES, ERR_REFERENTIAL_INTEGRITY, ERR_SCHEDULE_OVERLAP, ERR_SCHEDULE_GAP, ERR_COVERAGE_OVERLAP, ERR_PROPERTY_OVERCOMMITTED, ERR_ABSTRACTION_NOT_CERTIFIED, ERR_BILLING_NOT_INITIALIZED, ERR_OUTSTANDING_BILLING, ERR_OPEN_RECONCILIATION, ERR_OPEN_CHALLENGE, ERR_POOL_NOT_CLOSED, ERR_LEASE_NOT_ACTIVE, ERR_NOTIFICATION_NOT_YET_DUE, ERR_NOTIFICATION_WINDOW_MISSED, ERR_DATE_PASSED, ERR_NOT_EXERCISABLE, ERR_AMENDMENT_NOT_APPLIED, ERR_EXTENSION_MUST_EXTEND, ERR_EXPANSION_MUST_EXPAND, ERR_CONTRACTION_MUST_CONTRACT, ERR_AUDIT_WINDOW_CLOSED, ERR_MAX_ROUNDS_REACHED, ERR_INVALID_RESOLUTION_SIGN, ERR_RESOLUTION_EXCEEDS_TRUE_UP, ERR_REJECTION_REASON_REQUIRED.

**Roles (6, all `identity: opaque`)**: PlatformAdmin (property + clock), PortfolioManager (lease/amendment/reconciliation approve/challenge resolve), PropertyManager (critical dates, compliance, challenges, audits), LeaseAccountant (pools, billings, reconciliations post — but cannot approve), Abstractor (abstraction submit), Certifier (abstraction certify). Segregation enforced by `X-User-ID` comparison against `abstractor_user_id` / `posted_by_user_id`.

**Concurrency rules (2)**: `amendment-approve-stale-lease` and `lease-recertify-stale-lease`, both OCC on `Lease.version` with `expected_lease_version` payload field, error ERR_STALE_VERSION (412).

## §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances (2 per rule × 9 rules)

- **dual_variant_calc**: `recovery_billing_estimate_vs_final_with_gross_up` (400,000 estimate vs 791,667 final), `rent_roll_cash_vs_straight_line` (1,200,000 cash vs 1,260,000 straight-line; 60,000 delta).
- **combinatorial_formula**: `reconciliation_final_gross_up_waterfall` (mode (a): occupancy branch + tiered pro-rata + waterfall), `escalated_rent_per_line_rounding` (mode (b): per-line 333,366 × 3 = 1,200,099 vs sum-then-round 1,200,100).
- **non_linear_state_machine**: `tenant_challenge_cyclic_reopen` (cyclic, 3 rounds then ERR_MAX_ROUNDS_REACHED), `lease_parallel_dimensions` (status × abstraction_status × billing_posture independence).
- **transitive_cascade**: `amendment_rent_change_cascade` (depth-3: amendment→schedule line→effective_rent→cached_annual_rent, 1,260,000 → 3,240,000), `termination_cascade_to_billing_and_dates` (depth-2: terminate→billing VOID + critical date WAIVED).
- **priority_pair_validation_conflict**: `state_vs_business_safety_on_certify` (ERR_INVALID_STATE beats ERR_SEGREGATION_OF_DUTIES), `state_vs_business_fiscal_on_recon_close` (ERR_INVALID_STATE beats ERR_OPEN_CHALLENGE).
- **boundary_precision_check**: `critical_date_notify_window_start_boundary` (NOT_YET_DUE / OK / WINDOW_MISSED at exact days), `schedule_line_half_open_overlap_boundary` (adjacency allowed, 1-day overlap rejected).
- **cross_entity_state_dependency**: `reconciliation_post_requires_pools_closed` (Reconciliation × RecoveryPool), `amendment_apply_requires_lease_active` (Amendment × Lease).
- **resource_temporal_overlap**: `rent_schedule_line_half_open_overlap` (half-open interval), `compliance_doc_coverage_overlap_accepted_only` (status-filtered ACCEPTED-only overlap).
- **compensating_invariant**: `recovery_billing_issue_void_invariant` (cached_recovery_ytd_cents conserved: 400,000→800,000→400,000), `amendment_apply_reject_invariant_on_lease_version` (leased_sf=4000 and rent=1,200,000 conserved; only version advances).

## §1.9 SCAFFOLD_CORNER_DESIGN.yaml — 39 instances

- **entities** (9): property creation success + default posture, missing-field 400, not-found 404, lease computed-field zeros, escalation step conditional-required pct_bps/amount_cents, gross_up_floor default 9500, invalid total_sf, lease FK to property.
- **state_machines** (6): void-on-PAID terminal lockdown, LAPSED notify terminal, APPLIED amendment reject terminal, Reconciliation initial OPEN, AuditRight auto TIME_BARRED on window pass, abstraction cycle CERTIFIED→PENDING clears both user ids.
- **calculations** (2 + 4 stubs): occupancy_rate excludes DRAFT/TERMINATED (only ACTIVE counted: 4000 SF → 4000 bps), audit_window_close arithmetic (2027-03-15 + 365 = 2028-03-14 in leap year); 4 `excluded_because` stubs citing §1.8 instances.
- **validations** (10 + 8 stubs): OCC stale-version on amendment approve and reopen-abstraction (both 412), segregation-of-duties on certify and recon-approve, date_range commencement<expiration, abstraction-not-certified gate, outstanding-billing termination gate, extension-must-extend, expansion-overcommitted, resolution sign check, rejection-reason required, non-exercisable critical date kind; 8 `excluded_because` stubs for claims already covered by §1.8.
- **endpoints** (4): RBAC denials (LeaseAccountant→properties, Abstractor→activate, PortfolioManager→issue) + missing-auth 401.
- **cross_cutting_layers** (2): pagination limit/offset/has_more, default clock fixed at 2026-05-01T00:00:00Z.
- **consistency_model** (1): amendment apply atomic side effects (expiration update + old EXPIRATION waived + new EXPIRATION created).
- **errors** (3): schedule_gap on activation, referential integrity for cross-lease escalation_step, open_challenge blocks recon close.

## Step 3: Copy shared files — 2026-08-11T20:34:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1205_commercial_lease_abstraction/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T20:42:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/workspace/PRD.md` (56,062 bytes, 322 lines). The two withheld design files were never opened; no sibling task directories were touched.

## Summary of what was generated

**Section structure**
- §1 Introduction — 2 paragraphs (pain-point angle: abstraction, recovery reconciliation, critical-date risk, audit rights)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (headers `X-User-ID`/`X-User-Role`, all 6 roles individually named, all-`opaque` identity translated into prose, `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN`), 2.2 Response Structure (emitted verbatim from `section-2.2-response-structure.md`, untouched placeholders), 2.3 Pagination (`limit` default 10/min 1/max 100, `offset` default 0, `created_at`-ascending sort, `meta` fields), 2.4 Common Resource Properties (UUID `id`, `created_at`/`updated_at` ISO 8601 with 3 fractional digits, `version` increment semantics), 2.5 Nested Resource Retrieval (left-to-right: all 12 path-param ids named), 2.6 Monetary Precision (integer cents, round-half-up, basis-point denominator 10000, per-line-then-sum rounding pinned), 2.7 Logical Clock & Fiscal Calendar (startup default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`, clock-advance cascade enumeration), 2.8 Derived State Dimensions (three parallel Lease dimensions; full `billing_posture` derivation rules incl. the 60-day delinquency rule; `Property.posture` derivation), 2.9 Segregation of Duties, 2.10 OCC (exactly two guarded endpoints, `expected_lease_version`, `ERR_STALE_VERSION`/412), 2.11 Validation Pipeline Ordering (all 14 priorities in explicit sequence)
- §3 Business Logic — 9 subsections: 3.1 Portfolio Foundation, 3.2 Abstraction/Certification/Reopening, 3.3 Rent Schedules & Activation Gates, 3.4 Termination & Expiration, 3.5 Recovery Pools & Estimate Billing, 3.6 Year-End Reconciliation, 3.7 Critical Dates & Compliance, 3.8 Amendments, 3.9 Challenges/Audit Rights/Reporting
- §4 Endpoint table — 4 columns only (Method, Path, Description, Authorized Role(s)), all 63 endpoints, with status-code paragraph (201 creation / 200 modification)
- §5 Error Code Catalogue — 2 columns only, all 33 error IDs with HTTP statuses

**Entity coverage** — all 12 entities (Property, Lease, RentScheduleLine, EscalationStep, RecoveryPool, RecoveryBilling, Reconciliation, CriticalDate, ComplianceDoc, Amendment, TenantChallenge, AuditRight); all 86 required identifiers (entity fields + request-body keys + query params + path params + report-output keys) verified present as standalone backticked tokens.

**Calculation prose coverage** — all 7 calculations rendered as precise pseudocode-free prose: estimate billing (budget × pro-rata bps ÷ 10000 ÷ 12, recovery-structure recoverable sets for `NNN`/`MODIFIED_GROSS`/`GROSS`), reconciliation final (occupancy step, `CAM`/`UTILITIES` gross-up below `gross_up_floor_pct_bps` default 9500, waterfall allocation with period-12 remainder absorption, `true_up_cents` signed delta, `period_index` 13 true-up billing), per-line escalation (`FIXED_PCT`/`CPI_LOOKUP` pinned at 250 bps/`STEPPED_AMOUNT`), annual rent aggregation (half-open fiscal-year overlap, no proration), straight-line rent (exact-rational intermediate, both `basis` variants), 365-day audit window (no weekend roll, strict boundary), occupancy rate (with zero case).

**Validation/error coverage** — all 14 validation priorities with explicit ordering prose; every one of the 33 error IDs mentioned in §2/§3 adjacent to its trigger; all state-machine transitions with preconditions, side effects, and cascades (expiration auto-close, termination cascade, extension/rent-change cascades, challenge/audit settle cascades, 30-day escalation deadline, 3-round negotiation cap).

**Verification results** — Contract 1: 86/86 field names present, PASS; Contract 2: all validations/OCC rules/transitions/calculations/errors expressed, PASS; Contract 3: 501 §3 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path tokens, PASS. (Note: the first mechanical check pass produced a false alarm due to JSON code fences breaking backtick pairing in the checker script; re-running with fences stripped confirmed true PASS.)

## Step 5: Generate unit tests — 2026-08-11T21:11:00.000Z

All verification passed. Final summary:

## Files created

**`test_helpers/` (9 files, 51.9 KB)**
- `__init__.py` (1059) — barrel export: framework generics + PRD-specific
- `types.py` (7406) — 12 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version`), 16 status/enum classes, `UserRole`
- `api_client.py` (15530) — `ApiClient(GenericApiClient)` with 68 methods covering every PRD §4 endpoint incl. filtered-list GETs; `api_client` singleton
- `api_errors.py` (3604) — 33 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (7284) — `assert_{entity}` ×12 + lease cache invariant checker
- `factories.py` (3646) — 12 payload factories, input fields only
- `constants.py` (1396) — PERIODS_PER_YEAR=12, PRO_RATA_DENOM=10000, CPI_LOOKUP_BPS=250, DEFAULT_GROSS_UP_FLOOR_BPS=9500, AUDIT_WINDOW_DAYS=365, MAX_CHALLENGE_ROUNDS=3, DEFAULT_CLOCK_ISO
- `test_users.py` (2103) — `TEST_USERS` for all 6 roles (all `identity: opaque`, so shared constants are canonical) + 6 `make_<role>_headers(user_id)` builders used by segregation tests
- `fixtures.py` (13001) — 5 tiers: atomic builders, `setup_active_lease`, `setup_posted/approved/closed_reconciliation`, child-entity builders, composite challenge scenario

**`test_suite/` (13 files, 94.8 KB)** — `conftest.py` + `test_01_…` through `test_12_…` (properties/creation, abstraction, schedule/escalation, billing, activation/termination/occupancy, reconciliation, critical dates, compliance, amendments, challenges/audits, RBAC/platform, rent roll).

## Verification results
- `python3 -m py_compile` on all 22 `.py` files: **OK**
- Import check of all modules (framework mocked): **OK**
- `Design: Difficulty/` tags: **36**; `Design: Corner/` tags: **40**; total tests: **76**; every test has exactly one tag; all tags resolve to real instances with correct rule_id/section
- PRD-citation pass: **105/105 quoted sentences match PRD.md verbatim** (whitespace-normalized literal match)
- No `skip`/`skipif`/`xfail`; no scaffold/section-table references in generated code

## Per-instance disposition

**Queue A (Difficulty) — 18/18 emitted, 2 tests each (36 tests):**
dual_variant_calc: `recovery_billing_estimate_vs_final_with_gross_up` ✓, `rent_roll_cash_vs_straight_line` ✓ · combinatorial_formula: `reconciliation_final_gross_up_waterfall` ✓, `escalated_rent_per_line_rounding` ✓ · non_linear_state_machine: `tenant_challenge_cyclic_reopen` ✓, `lease_parallel_dimensions` ✓ · transitive_cascade: `amendment_rent_change_cascade` ✓, `termination_cascade_to_billing_and_dates` ✓ · priority_pair_validation_conflict: `state_vs_business_safety_on_certify` ✓ (PRD §2.11 explicitly pins the pipeline order, so the silence-pattern skip does not apply), `state_vs_business_fiscal_on_recon_close` ✓ · boundary_precision_check: `critical_date_notify_window_start_boundary` ✓, `schedule_line_half_open_overlap_boundary` ✓ · cross_entity_state_dependency: `reconciliation_post_requires_pools_closed` ✓, `amendment_apply_requires_lease_active` ✓ · resource_temporal_overlap: `rent_schedule_line_half_open_overlap` ✓, `compliance_doc_coverage_overlap_accepted_only` ✓ · compensating_invariant: `recovery_billing_issue_void_invariant` ✓, `amendment_apply_reject_invariant_on_lease_version` ✓.

**Queue B (Corner) — 39/39 non-stub instances emitted (40 tests; `certify_segregation_of_duties` got a second positive-path test):** all 9 entities, 6 state_machines, 2 calculations, 12 validations, 4 endpoints, 2 cross_cutting_layers, 1 consistency_model, 3 errors instances emitted. The 17 `excluded_because:` stubs were **not translated**; all 17 `difficulty_instance` cross-references verified to resolve.

## Two disclosed deviations
1. **`property_create_required_fields`** — emitted, but the `version == 1` sub-assertion was dropped: PRD §2.4 states version "increments by one with every mutation" without stating the initial value, so two PRD-only readers could legitimately ship 0- or 1-based versioning. All other assertions (201, server-minted `id`, `posture == OPERATING`, input echo) are verbatim PRD-covered and retained.
2. **Setup ordering** — several recipes called `/recovery-billings/{id}/issue` while the lease was still DRAFT, but PRD §3.5 states issuing "requires the lease's `status` to be `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`)". Fixtures therefore create the DRAFT billing first (satisfying the PRD §3.3 activation gate, which accepts `DRAFT` or `ISSUED`), activate, then issue. All asserted outcomes are unchanged; this only makes the prescribed end-states actually reachable under a PRD-faithful implementation.

## Step 6: Generate implementation — 2026-08-11T21:11:00.000Z

Implementation complete and verified. Summary below.

## Implementation Summary — task_1205_commercial_lease_abstraction

**Files created** under `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/workspace/implementation/` (23 files, all sizes in bytes):

```
 396 start.sh              (executable, -rwxrwxr-x)
  16 requirements.txt     (flask>=3.0,<4.0)
1833 app.py                (entry point, error handlers, blueprint registration)
2156 db.py                 (in-memory store dicts + logical clock, starts empty)
1605 errors.py             (33-entry error catalog + ApiError)
1210 response.py           (envelope: meta/api_request_id/api_request_timestamp, response_type, data)
8737 middleware.py         (auth step 1-2: X-User-Role check + per-endpoint RBAC table)
   0 routes/__init__.py
1243 routes/helpers.py     (404 lookups, paginated list helper)
2563 routes/properties.py  (properties + logical clock endpoint)
10271 routes/leases.py      (lease CRUD, abstract/certify/reopen, activate/terminate, rent-roll)
5719 routes/schedules.py    (rent schedule lines + escalation steps)
7392 routes/recovery.py     (recovery pools + billings, issue/mark-paid/void)
6076 routes/reconciliations.py (open/post/approve/close)
5332 routes/critical_dates.py  (CRUD + notify/exercise/lapse/waive)
4132 routes/compliance.py   (docs + start-review/accept/reject)
9103 routes/amendments.py   (propose/approve/apply/reject with OCC)
8246 routes/challenges.py   (tenant challenges, rounds, resolve/escalate/withdraw)
5475 routes/audits.py       (audit rights, fieldwork/findings/settle)
   0 services/__init__.py
8075 services/calc.py       (all 7 calculation rules, Decimal ROUND_HALF_UP, no floats)
5393 services/core.py       (derived billing_posture/posture, clock-driven transitions)
3799 services/validate.py   (body/date/enum/int validation, pagination params)
```

**Verification results:**

1. **py_compile**: all 21 `.py` files compile clean (`COMPILE OK` / `PY_COMPILE OK`).
2. **Smoke boot** (3 fresh boots on ports 18731/18732/18733): server boots via `bash start.sh`, binds `0.0.0.0:$PORT`, foreground via `exec`. Verified: property create (201, envelope correct), empty-list pagination meta (`limit/offset/total_count/has_more`), `ERR_UNAUTHENTICATED` (missing role), `ERR_FORBIDDEN` (wrong role), `ERR_NOT_FOUND`, clock set, full lifecycle (abstract → certify with segregation enforced → schedule line with `ERR_SCHEDULE_OVERLAP` → billing estimate = `120000*5000/10000/12 = 5000` → activate → issue → rent-roll cash + straight_line → occupancy report `5000 bps` → pool actuals → reconciliation post `true_up_cents=137500, gross_up_applied=True` → approve segregation → close `closed_date` → audit right `window_close_date=2027-05-01` → amendment OCC `ERR_STALE_VERSION` then approve/apply with exactly +1 version increment each → EXTENSION cascade creating new EXPIRATION CriticalDate).
3. **Route comparison (verbatim)**:
   - registered flask routes: **80**
   - scaffold §1.5 endpoints: **80**
   - missing: **0**; extra: **0** → **MATCH** (Flask's built-in `/static/<path:filename>` route was disabled via `static_folder=None` so the count is exactly the declared surface).

**Key design points**: in-memory dicts only (no disk/SQLite), zero seeding at startup; logical clock defaults to `2026-05-01T00:00:00Z` and only advances via `POST /lease-admin/_clock/set_current_utc`, which triggers the date-driven cascades (lease EXPIRED, CriticalDate LAPSED, ComplianceDoc EXPIRED, AuditRight TIME_BARRED with ESCALATED→UNDER_REVIEW challenge reversion); validation pipeline follows PRD §2.11 ordering (auth → RBAC → existence → shape → temporal → state → segregation → referential → overlap/capacity → fiscal → window → OCC); all money math is integer/Decimal round-half-up with per-line rounding pinned; `start.sh` guards the pip install behind an `import flask` check so per-test reboots are fast.

## Step 7: Run tests and iterate — 2026-08-11T21:39:00.000Z

## Summary

- **Iterations run**: 4 sweeps (8 parallel rounds each) to reach a stable 76/76 × 8.

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**:
  - `constants.py`: Changed `FISCAL_YEAR` 2027→2026, `COMMENCEMENT_DATE` 2027-01-01→2026-01-01, `EXPIRATION_DATE` 2027-12-31→2026-12-31, `SCHEDULE_PERIOD_START/END` shifted to 2026 — at the PRD's fixed default clock `2026-05-01T00:00:00Z` (§2.7) and `fiscal_year_end_month=12`, the current fiscal year is 2026, so the fixture's lease term and billing fiscal_year must live in 2026 to satisfy PRD §3.3's activation gate ("at least one RecoveryBilling for the current fiscal year must already exist in `DRAFT` or `ISSUED` status").
  - `fixtures.py`: Added `create_tenant_challenge_payload` to the `from .factories import (...)` list — the symbol was used at line 319 but never imported, producing `NameError` in five challenge/audit tests.

- **Fixes applied to `test_suite/`**:
  - `test_03_rent_schedule_and_escalation.py` / `test_04_recovery_billing.py` / `test_05_activation_termination_occupancy.py` / `test_06_reconciliation.py`: Flipped hardcoded `fiscal_year=2027` → `2026` (or reverted to the correct FY for the schedule under test) to align with the fixture's new FY2026 window.
  - `test_07_critical_dates.py`: Shifted due_date / set_clock references from 2027 → 2026 dates so the PENDING critical dates remain in a window where the lease is still ACTIVE (the lease now expires 2026-12-31).
  - `test_09_amendments.py::test_amendment_apply_atomic_side_effects`: Changed the EXPIRATION critical date `due_date` from `2027-12-31` → `2026-12-31` to match the lease's new expiration, so the amendment cascade can find and WAIVE it per PRD §3.8.
  - `test_09_amendments.py::test_amendment_extension_must_extend`: Changed `new_expiration_date` to `2026-06-01` so it is strictly earlier than the new current expiration `2026-12-31` and the ERR_EXTENSION_MUST_EXTEND gate actually fires.
  - `test_09_amendments.py::TestRentChangeCascade._setup`: Changed `recovery_structure` from `GROSS` → `NNN` and added explicit `commencement_date` / `expiration_date` / `fiscal_year=2027` for the 2027 schedule; `GROSS` blocks every pool category from billing (PRD §3.5), so the activation gate could never be satisfied under `GROSS` — the fixture precondition was unsatisfiable.

- **Fixes applied to `implementation/`**:
  - `services/calc.py::compute_reconciliation_final`: Fixed the waterfall allocation to key on `period_index` rather than list position. PRD §3.6 step 4 reads "rows one through eleven each receive the yearly share divided by twelve and rounded half-up, and the twelfth row receives the remainder". The previous implementation assigned "last row gets remainder" by list position, which misallocates when the pool has fewer than 12 rows (e.g., only period 1 → that row got the full year share instead of the monthly).

- **Final state**: All 8 rounds of the stability sweep report `passed=76, failed=0, errors=0`. (Verified on disk: results.1.json–results.8.json each 76/76.)

## Step 8: Finalize PRD — 2026-08-11T21:48:00.000Z

## Summary

**Produced**: `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md = 322 lines, PRD_FINALIZED.md = 322 lines → 0.0% delta (all three edits are sentence-level insertions/revisions inside existing single-line paragraphs; no sections added or removed).

### Changes (one bullet each)

- **§2.7** — *insert* — Added the fiscal-year labeling rule: label Y ends on the last day of `fiscal_year_end_month` within calendar year Y and begins the day after the prior fiscal year's end; spans are half-open, so "the fiscal year's start" is the first day and "the fiscal year's end" in §3 overlap tests is the exclusive boundary (day after the last day); "the current fiscal year" is the labeled FY whose span contains the current logical date — `implementation/services/calc.py:34-60` (`fiscal_year_window`, `current_fiscal_year`)
- **§3.5** — *insert* — Added that creating a RecoveryBilling against a pool whose category is not recoverable under the lease's `recovery_structure` is rejected with `ERR_REFERENTIAL_INTEGRITY` — `implementation/routes/recovery.py:99-105`
- **§3.6 (step 4)** — *revise* — The waterfall is now keyed on each row's `period_index` (rows with `period_index` 1–11 get the rounded monthly amount; the row with `period_index` 12 gets the remainder = yearly share minus 11× the rounded monthly amount), and the exact-sum invariant is scoped to "when all twelve monthly rows are present" instead of universally — `implementation/services/calc.py:203-213`

### Step-7 items with no PRD edit (with reason)

- `fixtures.py` missing import — pure fixture bug (NameError), no behavioral content.
- `test_03/04/05/06` FY 2027→2026 flips — downstream consequences of the §2.7 derivation (Edit 1), no separate PRD content.
- `test_07` critical-date shifts and `test_09` amendment `due_date`/`new_expiration_date` changes — fixture realignment to the new FY2026 lease window; §3.7/§3.8 already pin lapsing, the EXPIRATION-waiver cascade, and `ERR_EXTENSION_MUST_EXTEND`.

### Per-edit pre-edit search log

**Edit 1 (§2.7 fiscal-year derivation)**
- (a) Subject: mapping from `fiscal_year` label to calendar window, and derivation of "the current fiscal year" from the logical clock + `fiscal_year_end_month`.
- (b) Enumerated paths: `services/calc.py:34-60` (both helpers, incl. docstring rule); all callers of `current_fiscal_year` — `calc.py:95` (cached rent), `services/core.py:62` (`cached_recovery_ytd_cents`), `routes/leases.py:191` (activation billing gate); all callers of `fiscal_year_window` — `calc.py:96`, `calc.py:140` (`occupancy_rate_bps`, feeding `routes/properties.py:75` and reconciliation step 1), `routes/leases.py:248` (rent-roll cash and straight-line via `calc.py:81-120`). Verified numerically for m=12 and m=6 that the label equals the calendar year of the FY's end and the window is half-open.
- (c) Adjustment: my first draft said only "ends on the last day of that month"; I added the half-open-span gloss because §3.1/§3.3 overlap tests ("falls before the fiscal year's end") compare against the *exclusive* end boundary in the impl (`period_start < fy_end` where `fy_end` is the day after the last day) — without the gloss, a lease commencing exactly on the FY's last day would be mis-described.

**Edit 2 (§3.5 recoverability rejection)**
- (a) Subject: consequence of creating a RecoveryBilling against a non-recoverable pool category.
- (b) Enumerated paths: `routes/recovery.py:90-119` (only billing-creation endpoint; rejects at `recovery.py:103-105` with `ERR_REFERENTIAL_INTEGRITY`); `services/calc.py:14-18, 132-133` (recoverability table); `services/calc.py:167-170` (reconciliation filters pools to recoverable categories); `routes/reconciliations.py:96-101` (true-up anchor pool chosen among recoverable pools).
- (c) Adjustment: kept the existing "under `GROSS` no recoveries are billed at all" verbatim and scoped the new sentence strictly to creation rejection, so the reconciliation-side filtering and anchor-pool selection (governed by §3.6 text I did not change) are not mis-described.

**Edit 3 (§3.6 waterfall keying)**
- (a) Subject: how the yearly share waterfall assigns `final_cents` across a pool's billing rows.
- (b) Enumerated paths: `services/calc.py:199-213` (sole writer of `final_cents`: rows sorted by `(period_index, created_at)`; `period_index` 1–11 → monthly; 12 → `year_share - 11*monthly`; other indices, e.g. 13, untouched); `calc.py:215-216` (null `final_cents` counts as 0 in `sum_final`); `routes/reconciliations.py:88-92` (touch bookkeeping); `reconciliations.py:95-114` (period-13 true-up row created after computation with `final_cents` null); `routes/recovery.py:114` (new billings start null).
- (c) Adjustment: replaced the positional reading ("rows one through eleven / the twelfth row") with explicit `period_index` keying; softened "so the rows sum to the yearly share exactly" to "when all twelve monthly rows are present" because with a partial row set (e.g., only period 1, as in `test_final_variant_uses_grossed_up_actuals`) the impl allocates only the monthly amount and the total need not equal the yearly share; deliberately silent on rows with `period_index` outside 1–12 (they keep `final_cents` null) to stay under-determined rather than introduce a false universal claim.

## Step 9: Complete PRD — 2026-08-11T22:04:00.000Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/workspace/PRD_COMPLETED.md`.

**Source/delta:** `PRD_FINALIZED.md` (322 lines, 56,967 chars) → `PRD_COMPLETED.md` (322 lines, 61,308 chars; +4,341 chars, 30 paragraphs touched, no sections added/removed).

**Counts:** 20 ambiguity-pins, 10 mismatch-revisions.

**Mismatch revisions:**
- §2.1 — revise — PRD made `X-User-ID` mandatory; impl enforces only `X-User-Role` — `middleware.py:124-130` (`current_role` checks role only; `current_user_id` may return None).
- §3.3 — revise — cache "refreshed on line creation or deletion" but no delete endpoint exists — `routes/schedules.py` (no DELETE route; §4 table has none).
- §3.4 — revise — termination gate dropped "with an unpaid amount greater than zero"; impl blocks on any `ISSUED` billing — `routes/leases.py:213-216`.
- §3.4 — revise — expiration auto-close of reconciliations records no `closed_date` — `services/core.py:92-96`.
- §3.5 — revise — issue/void recompute `cached_recovery_ytd_cents` as the current-FY ISSUED/PAID total rather than incrementally adding/subtracting — `routes/recovery.py:166,196`, `services/core.py:58-69`.
- §3.5 — revise — a `DISPUTED` billing returns to `ISSUED` only via resolve/withdraw, not via audit settlement — `routes/audits.py:113-144` (no billing release), `routes/challenges.py:203-210`.
- §3.7 — revise — `linked_amendment_id` is accepted unvalidated at creation (not "stays null until exercised") — `routes/critical_dates.py:36,49`.
- §3.7 — revise — clock expiry hits `SUBMITTED`, `UNDER_REVIEW`, and `ACCEPTED` docs (PRD omitted `UNDER_REVIEW`), and posture recomputes for any expiring doc's lease — `services/core.py:111-119`.
- §3.9 — revise — removed the unimplemented 30-day escalation deadline; `ESCALATED` reverts to `UNDER_REVIEW` only on audit time-bar — `routes/challenges.py:170-177`, `services/core.py:122-133`.
- §3.9 — revise — audit window for an auto-closed reconciliation (no `closed_date`) is computed from the invocation-time logical date — `routes/audits.py:40-41`.

**Ambiguity pins:**
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — `services/validate.py:91-113`.
- §2.3 — insert — list sort tie-break by `id` ascending — `routes/helpers.py:38`.
- §2.3 — insert — `has_more` = `offset + page_len < total_count`; filters are equality matches; undefined query params ignored — `response.py:34`, `routes/helpers.py:31-42`.
- §2.4 — insert — `version` starts at 1 — `db.py:88`.
- §2.4 — insert — `created_at`/`updated_at` drawn from logical clock, +1ms per mutation; undefined body fields ignored — `db.py:61-66,85-94`.
- §2.5 — insert — undeclared path or unsupported method → `ERR_NOT_FOUND` (404) — `app.py:40-47`.
- §2.7 — insert — clock advance also re-derives every lease's `billing_posture` (delinquency flips) — `services/core.py:137-138`.
- §2.8 — insert — `FROZEN` takes precedence over `DELINQUENT` — `services/core.py:14-30`.
- §2.9 — insert — absent `X-User-ID` skips the segregation check; counterpart stored null — `routes/leases.py:127-128`, `routes/reconciliations.py:125-126`.
- §3.1 — insert — occupancy-report requires `fiscal_year` (2000–2100) else `ERR_INVALID_REQUEST` — `routes/properties.py:72-74`.
- §3.3 — insert — duplicate `step_index` → `ERR_INVALID_REQUEST`; schedule-line collection filterable by `lease_id`/`escalation_step_id`; step collection by `lease_id` — `routes/schedules.py:108-111,80-84,153-156`.
- §3.5 — insert — `period_index` is any integer ≥ 1 (13 = true-up), no pool/period uniqueness — `routes/recovery.py:96`.
- §3.6 — insert — only recoverable-category pools enter the posting computation; zero-occupancy gross-up divides by 10000; rows with `period_index` outside 1–12 keep `final_cents` null; true-up row's `estimate_cents` = delta and `pool_id` = lexicographically smallest recoverable pool id (null if none) — `services/calc.py:167-217`, `routes/reconciliations.py:95-114`.
- §3.6 — insert — closing records `closed_date` (current logical date) — `routes/reconciliations.py:148`.
- §3.7 — insert — manual lapse on/before `due_date` → `ERR_DATE_PASSED` — `routes/critical_dates.py:134-136`.
- §3.8 — insert — proposals accepted regardless of lease status; apply does not re-check lease status; extension-created EXPIRATION date gets `advance_notice_days` 0 — `routes/amendments.py:24-82,132-136,188-197`.
- §3.9 — insert — challenges may reference a reconciliation in any status (`CHALLENGED` transition only from `APPROVED`); resolve requires `UNDER_REVIEW`; audit invoke against non-`CLOSED`/foreign reconciliation → `ERR_REFERENTIAL_INTEGRITY`; settle sets rejected challenges' `resolution_delta_cents` to 0; settle does not release disputed billings; rent-roll requires `fiscal_year` (2000–2100), `basis` defaults to `cash`, invalid basis → `ERR_INVALID_REQUEST` — `routes/challenges.py:37-40,66-68,135`, `routes/audits.py:31-37,126-132`, `routes/leases.py:241-246`.

All other impl behaviors (endpoint/role matrix, pipeline ordering, escalation formulas, occupancy math, waterfall allocation, state machines, error catalog) were verified as already uniquely pinned by the PRD.

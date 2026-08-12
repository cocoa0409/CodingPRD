# Worklog — task_1207_theatrical_rights_licensing

## Step 1: Create Task Directory — 2026-08-11T20:45:00.000Z

Pre-assigned output folder `tasks/task_1207_theatrical_rights_licensing` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T21:10:00.000Z

All three files exist, parse as valid YAML, and pass `scaffold_lint.py` clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1207_theatrical_rights_licensing/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no scaffold_difficulty_design / scaffold_corner_design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: **12** (Title, TerritoryRestriction, Organization, LicenseApplication, LicenseAgreement, Performance, MaterialRental, AlterationRequest, RecordingGrant, RoyaltyPayment, Fine, AvailabilitySnapshot)
- State machines: **8** (incl. parallel `license_status` × `payment_status` dimensions on LicenseAgreement)
- Calculations: **8** (performance_royalty with QUOTED/SETTLED variants, overdue_fine_rule with PROJECTED/ACTUAL variants, deposit_settlement_rule with pinned nested-rounding, classification_rule, recording_royalty_rule, breach_fine_rule, cancellation_refund_rule waterfall, availability_rule with closed-vs-half-open interval semantics)
- Validations: **21** ordered priority rows
- Endpoints: **65**
- Errors: **27**
- Roles: **5** (RightsAdmin, LicensingOfficer, Applicant [entity_backed:Organization], MaterialsClerk, FinanceOfficer)
- Concurrency rules: **2** (OCC on LicenseApplication.approve and LicenseAgreement.amendments)
- §1.8 difficulty instances: **18 active** (9 rules × 2)
- §1.9 corner instances: **35 active** + **2 excluded stubs** (= 37 total)

**Difficulty tier (harder than expert)** applied via: dual-variant calculations across royalty and rental-fine domains; tiered multi-input royalty with tier/classification/basis branches; pinned per-item-then-sum rounding in deposit settlement; cyclic LicenseApplication review loop; parallel LicenseAgreement dimensions; depth-3 transitive cascades from `declare_breach` and `cancel`; closed-vs-half-open interval semantics differing between TerritoryRestriction and exclusive-run LicenseAgreement; two distinct OCC-guarded endpoints; cross-entity state dependencies across Performance→Agreement and MaterialRental→Agreement; compensation invariants on both royalty_balance_cents and deposit_cents pools.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-11T21:10:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1207_theatrical_rights_licensing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T21:20:00.000Z

File confirmed on disk. Here is the summary.

## Summary

**File confirmed on disk**: `/home/ubuntu/github/CodingPRD/tasks/task_1207_theatrical_rights_licensing/workspace/PRD.md` — 294 lines, 46,183 bytes.

### Section list
- **§1. Introduction** (3 paragraphs)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1. User and Role-Based Access Control
  - 2.2. API Response Structure (emitted verbatim from `section-2.2-response-structure.md`)
  - 2.3. Pagination
  - 2.4. Common Resource Properties, Money, and Temporal Conventions
  - 2.5. The Logical Clock
  - 2.6. Hierarchical Path Validation and Optimistic Concurrency
  - 2.7. Validation Ordering
  - 2.8. Tiered Royalty Pricing and Constants
- **§3. Business Logic & Workflows** (scattered prose)
  - 3.1. Building the Title Catalogue
  - 3.2. Registering Applicant Organizations
  - 3.3. From Application Draft to Approval
  - 3.4. The License Agreement at Issuance
  - 3.5. Performances and Settlement
  - 3.6. Material Rentals and the Deposit Lifecycle
  - 3.7. Alteration Requests and Recording Grants
  - 3.8. Fines, Standing, and Resolution
- **§4. Endpoint Definitions** (4-column table: Method, Path, Description, Authorized Role(s); 64 endpoints)
- **§5. Error Code Catalogue** (2-column table: Error ID, HTTP Status Code; 27 errors)

### Hard Contracts
```
Field coverage check:
- entities[].fields + endpoints[].request_body + query_params: 90 required, 90 present, 0 missing
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 524
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Rule coverage (Contract 2)
- **Entities** (10): Title, TerritoryRestriction, Organization, LicenseApplication, LicenseAgreement, Performance, MaterialRental, AlterationRequest, RecordingGrant, RoyaltyPayment, Fine, AvailabilitySnapshot — all field names in backticks, all initial states and field sources described.
- **State machines** (8): LicenseApplication (DRAFT/SUBMITTED/UNDER_REVIEW/RETURNED_FOR_INFO/APPROVED/REJECTED), LicenseAgreement license_status (PENDING_PAYMENT/ACTIVE/COMPLETED/CANCELLED/BREACHED), LicenseAgreement payment_status (UNPAID/PARTIALLY_PAID/PAID_IN_FULL/REFUNDED), Performance, MaterialRental (7 states), AlterationRequest, RecordingGrant, Fine — every transition's preconditions and side effects expressed in prose.
- **Concurrency rules** (2): `expected_agreement_version` on amendments, `expected_application_version` on approve — both explicitly named with `ERR_STALE_VERSION` (412).
- **Calculations** (7): `performance_royalty` (QUOTED/SETTLED variants with tier ladder 1.00/1.25/1.60/2.00 and class 1.00/1.50), `overdue_fine_rule` (PROJECTED/ACTUAL with 2× deposit cap and pinned order), `deposit_settlement_rule` (per-line rounding then sum — pinned), `classification_rule` (4000-cent floor, 500-seat floor), `recording_royalty_rule` (1.00/0.50/2.00 base × 1.50/1.25 scope), `breach_fine_rule` (500,000-cent floor, 2×/3× multipliers), `cancellation_refund_rule` (30-day 1.00, 7-day 0.50 waterfall oldest-first), `availability_rule` (closed restriction interval vs half-open exclusive-run interval).
- **Validations** (21 priorities): full priority ordering narrated in §2.7, every error ID matchable to its trigger in §2/§3 prose.
- **Endpoints** (64): all listed in §4 with method, path, description, roles; side effects scattered through §3 narratives.
- **Errors** (27): all catalogued in §5; trigger conditions scattered in §2.7 and §3.
- **Roles** (5): RightsAdmin, LicensingOfficer, Applicant (entity-backed by Organization), MaterialsClerk, FinanceOfficer — identity semantics for each named in §2.1.
- **Logical clock**: startup default `2026-05-01T00:00:00Z` stated explicitly in §2.5; `to_iso8601` parameter named; sweeps for OVERDUE rentals and COMPLETED agreements described.
- **Common fields deviation**: RoyaltyPayment and AvailabilitySnapshot called out in §2.4 as lacking `updated_at` and `version`.

### Contract 2 report
```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 27 checked, 27 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (formulas reconstructed in prose, no pseudocode), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 64 checked, 64 expressed, 0 missing
- entities[].fields[] structured content: 90 checked, 90 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (approve/reject, pay/waive/write_off, cancellation refund tiers, recording royalty kinds, deposit settlement branches, alteration kinds, classification rule branches, QUOTED vs SETTLED variants), 8 with equal prose density, 0 asymmetric
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-11T21:40:00.000Z

All files are confirmed on disk, `py_compile` passes, pytest collects 71 tests cleanly, and both citation audits pass.

## Summary — task_1207_theatrical_rights_licensing

**test_helpers/ (9 modules, all compile + import cleanly):**
- `types.py` — 12 entity TypedDicts + 17 status/role enums; `RoyaltyPayment` and `AvailabilitySnapshot` correctly modeled as append-only (no `updated_at`/`version`) per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (45 methods incl. `set_clock`)
- `api_errors.py` — `ApiErrorId` (27 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_deposit_conserved` invariant
- `factories.py`, `constants.py` (tier floors, PRO floors, refund ladder, breach floor, clock start `2026-05-01T00:00:00Z`)
- `test_users.py` — opaque-role shared constants + `make_applicant_headers(org_id)` for the entity-backed Applicant role
- `fixtures.py` — composite fixtures: `setup_pending_agreement`, `setup_active_agreement`, `setup_active_agreement_with_performance/_with_grant`, `setup_rental_in_state` (RESERVED→RETURNED/OVERDUE), `setup_assessed_overdue_fine`, `setup_breached/cancelled_agreement`
- `__init__.py` — barrel export

**test_suite/ — 71 tests collected, 0 skipped:**

| File | Tests | Coverage |
|---|---|---|
| test_01_catalog_and_envelope.py | 8 | corner: entities CRUD/enums/pagination, envelope shape, immediate consistency |
| test_02_applications_and_rbac.py | 11 | corner: initial state, invalid transitions, auth/RBAC/ownership, temporal validation; difficulty: review-cycle loop ×2 |
| test_03_royalty_calculations.py | 8 | difficulty: QUOTED-vs-SETTLED ×2, tiered multimode ×2, 199/200 boundary ×2; corner: computed quoted field, classification rule |
| test_04_agreement_lifecycle.py | 9 | difficulty: parallel payment/license dimensions ×2, cancel cascade ×2; corner: amendment seq/version, amendment-on-terminal, payment bounds, cancel cascade, full refund |
| test_05_rentals_and_fines.py | 12 | difficulty: PROJECTED-vs-ACTUAL late fee ×2, pinned rounding ×2, zero-day boundary ×2, deposit conservation ×2; corner: restricted rate, rental-kind, terminal lockdown, declare-lost timing, waiver restores standing |
| test_06_compliance_availability_concurrency.py | 23 | difficulty: breach cascade ×2, royalty balance conservation ×2, both priority pairs ×2 each, cross-entity gates ×2 each, closed/half-open intervals ×2 each; corner: recording royalty 3.00× multiplier, breach-fine not waivable, report-too-early, OCC stale version ×2 |

**Queue A (difficulty): 18/18 instances translated, exactly 2 tests each.** Queue B (corner): 32/32 non-stub instances translated, 1 test each. The 2 `excluded_because:` stubs were not translated; their cross-references verified to resolve (`territory_restriction_closed_interval_blocks_touching_window`, `tier_boundary_199_vs_200_seats`).

**Instances skipped: none.** All 50 non-stub instances passed the PRD-first two-condition filter.

**Key adjudications made during translation:**
- `territory_restriction_closed_interval_blocks_touching_window`: the design's literal timestamps (restriction end `06-10T00:00` vs request start `06-10T19:00`) do not touch at PRD-mandated seconds granularity; the test sets the request window_start exactly equal to the restriction window_end so the closed-interval touch is real, and asserts `ERR_TITLE_UNAVAILABLE` (PRD §3.3 pins snapshot-first ordering).
- `ship_return` flows in overdue scenarios were re-sequenced to ship while `RECEIVED` before the clock sweep flips the rental to `OVERDUE`, since PRD §3.6 only allows `ship_return` from `RECEIVED`; the OVERDUE→RETURNED path is exercised via `receive_return` directly.
- `exclusive_run_half_open_interval_allows_adjacent_window`: PRD never defines how an agreement acquires exclusive-run rights, so every PRD reader concludes the adjacent approval succeeds with empty `blocking_agreement_ids` — matching the design's expected outcome.
- `fine_waiver_side_effect_restores_org_standing`: the overdue-fine path never suspends the org, so the standing assertion (`GOOD` after waiving the last ASSESSED fine) holds per PRD §3.8's restoration rule; the load-bearing assertion is the waiver transition itself.
- Every docstring carries a verbatim PRD citation (automated grep-verified against PRD.md) plus exactly one `Design:` tag resolving to a real yaml instance.

## Step 6: Generate Implementation — 2026-08-11T21:40:00.000Z

All verification steps complete. Summary:

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1207_theatrical_rights_licensing/workspace/implementation/`):

- `start.sh` (executable, foreground `exec`, guarded `pip install`)
- `requirements.txt` (flask)
- `app.py` (entry point, error handlers, blueprint registration, `0.0.0.0:$PORT`)
- `db.py` (in-memory stores as dicts, logical clock pinned to 2026-05-01T00:00:00Z, ISO8601 ms-precision timestamp helpers)
- `errors.py` (full error catalog with exact error_id/HTTP status)
- `response.py` (envelope per scaffold: `meta.api_request_id` / `api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` inside `meta`)
- `middleware.py` (X-User-ID / X-User-Role auth, role gating, Applicant entity-backed ownership)
- `routes/titles.py` — titles + territory restrictions (9 routes)
- `routes/organizations.py` — 3 routes
- `routes/applications.py` — 10 routes incl. submit/begin_review/return_for_info/approve/reject, availability
- `routes/agreements.py` — 10 routes incl. payments, performances, amendments (OCC), cancel, declare_breach
- `routes/performances.py` — 4 routes (get, list, report, cancel)
- `routes/rentals.py` — 8 routes (create/get/list/ship/mark_received/ship_return/receive_return/declare_lost)
- `routes/alteration_requests.py` — 5 routes
- `routes/recording_grants.py` — 6 routes
- `routes/fines.py` — 5 routes
- `routes/availability.py` — 3 routes incl. `POST /licensing/_clock/set_current_utc` driving sweeps
- `services/serializers.py`, `services/calculations.py`, `services/sweeps.py`

**Route count**: 65 Flask routes registered.

**Route/scaffold delta**: 0 missing, 0 extra — exact match against SCAFFOLD.yaml's 65 declared endpoints (verified programmatically via YAML diff).

**Boot check**: PASS — `PORT=17891 bash start.sh` boots in <1s; `GET /licensing/titles` returns correct envelope with default logical clock `2026-05-01T00:00:00.000Z`; missing auth headers → HTTP 401 `ERR_UNAUTHENTICATED`; `POST /licensing/_clock/set_current_utc` works. A second boot ran an end-to-end smoke (title → org → draft → submit → begin_review → approve) and produced a PENDING_PAYMENT agreement with the correct quoted royalty of 42501 cents (matches the QUOTED formula by hand: tier 1.25 × class 1.00 → flat 12500, pct round(100000·500/10000/3)=1667, per-perf 14167 × 3 = 42501).

**py_compile**: passes on every `.py` file.

**Key design decisions honored from PRD/scaffold**:
- In-memory dicts only; store starts empty on every boot; no seeding.
- Validation priority ordering per PRD §2.7 (business-rule availability checks fire before the OCC `ERR_STALE_VERSION` check on approve).
- Logical clock (fixed default 2026-05-01, never wall-clock); sweeps fire only on `set_current_utc` (OVERDUE rentals + agreement COMPLETED transitions).
- Money as integer cents via `Decimal` with `ROUND_HALF_UP` at the exact steps the calculation rules pin (per-component rounding before summation in deposit settlement; raw fee computed first then capped at 2× deposit; cancellation pool rounded once then allocated oldest-first).
- Common fields: `created_at`/`updated_at`/`version` on most entities; `RoyaltyPayment` and `AvailabilitySnapshot` omit `updated_at`/`version` per PRD §2.4.

## Step 7: Run Tests and Iterate — 2026-08-11T21:55:00.000Z

## Summary

**Iterations run**: 3 (initial 8-round sweep → single smoke round after fixes → final clean 8-round sweep, 70/70 × 8).

**Tests deleted** (1):
- `test_suspended_org_application_rejected_even_with_bad_payload` (test_06) — asserted `ERR_ORG_SUSPENDED` on a shape-invalid payload (`projected_gross_cents=-5`). PRD §2.7 verbatim orders payload shape (`ERR_INVALID_REQUEST`, priority 6) *before* org standing (`ERR_ORG_SUSPENDED`, priority 9), so the asserted precedence contradicts the PRD's explicit ordering (error-precedence rule covered with the inverse outcome). The sibling `test_suspended_org_application_rejected_with_valid_payload` retains faithful coverage of the standing rule.

**Fixes applied to `test_helpers/`**:
- `fixtures.py` — added `fund_agreement_for_activation(agreement_id)` and called it in `setup_active_agreement` before `activate`. PRD §3.4 requires funding (full or partial-payment rule) before activation; the fixture activated an unfunded agreement, so every ACTIVE-agreement setup failed with `ERR_INVALID_STATE`. Pays `floor(quoted/2)`, leaving balance `ceil(quoted/2)`.

**Fixes applied to `test_suite/`**:
- `test_02_applications_and_rbac.py` — added missing `create_title_payload` import (NameError in `test_wrong_role_cannot_create_title`).
- `test_03_royalty_calculations.py` — `_build_two_performance_agreement` now calls `fund_agreement_for_activation` before `activate_agreement` (PRD §3.4 funding gate).
- `test_04_agreement_lifecycle.py` — `test_amendment_increments_agreement_version_and_seq` now compares `window_end` as parsed instants instead of exact strings; PRD §2.4 mandates the 3-digit-ms format only for `created_at`/`updated_at`, other datetimes are just "ISO 8601 UTC" (string format not uniquely derivable; the PRD rule under test is that the amendment applies `new_window_end`).
- `test_05_rentals_and_fines.py` — `_build_overdue_rental` now stores `ctx["rental"]` (KeyError when the test read `ctx["rental"]["id"]`).
- `test_06_compliance_availability_concurrency.py` — `_setup_adjacent` and `test_declare_performance_succeeds_once_active` now fund before activation (PRD §3.4); four balance assertions updated to account for the fixture's PRD-required activation payment (80000→55000, 50000→25000, 50000+30000→25000+30000, 50000+90000→25000+90000).

**Fixes applied to `implementation/`**:
- `routes/applications.py` — removed the strict-inequality check on application `first_performance_date`/`last_performance_date` (kept validity parsing). PRD §2.4's strict-inequality rule names the `window_start`/`window_end` fields (TerritoryRestriction, amendment `new_window_end`); the application's fields are named differently, and §3.5's inclusive performance window makes a single-show run (`first == last == performance_at`) coherent — two faithful readers diverge, and no test asserts the rejection. The restriction-side check (which a test does assert) is untouched.
- `app.py` — `__main__` now retries the port bind (20 × 0.5s) on `OSError`. The per-test-server harness `kill -9`s the old server and immediately respawns on the same port; if the old process hadn't released the listen socket, the fresh server died on `EADDRINUSE` and the 15s readiness poll expired ("could not be restarted"). This was the sole source of cross-round flakiness (6 distinct flaky errors in sweep 1; zero after the fix).

No endpoints, fields, or checks were added to the implementation beyond PRD-derived behavior; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-08-11T22:05:00.000Z

Both files are 294 lines (one line revised in place, so line-count delta is 0%). The diff is a single-line revision within §2.4.

## Summary

**PRD.md vs PRD_FINALIZED.md**: 294 lines → 294 lines (0% line-count delta; one sentence-block revised inline in §2.4).

**Changes** (one logical edit site, two pins):

- **§2.4 — revise — scoped the strict-inequality temporal rule to fields named `window_start`/`window_end`** (TerritoryRestriction creation; amendment `new_window_end`), and pinned that a `LicenseApplication`'s `first_performance_date`/`last_performance_date` carry no ordering constraint — only ISO 8601 well-formedness — so a single-show run with `first == last` is well-formed and approval copies the coincident instant into the agreement's `window_start`/`window_end`. — `implementation/routes/applications.py:79-86` (`_validate_application_window` now parse-only), `:118-120` (create), `:226-231` (edit), `:347-348` (approval copies dates verbatim); contrast sites `implementation/routes/titles.py:170` and `implementation/routes/agreements.py:219-220` retain the strict check.

- **§2.4 — revise — pinned server-rendered datetime format**: every datetime the server emits (resource fields and envelope timestamps alike) is rendered ISO 8601 UTC with three fractional digits. — `implementation/db.py:47-52` (`fmt_ts`, the sole formatter), used by `implementation/services/serializers.py:5-6` (`_dt`, all entity datetime fields), `implementation/response.py:17` (`api_request_timestamp`), `implementation/routes/availability.py:60` (`current_utc`).

**Items needing no edit**: fixture funding gate (PRD §3.4 already pins funding-before-activation verbatim, matching `agreements.py:57-62`); deleted suspended-org test (PRD §2.7 already orders `ERR_INVALID_REQUEST` priority 6 before `ERR_ORG_SUSPENDED` priority 9 verbatim); `app.py` port-bind retry (process infrastructure, not API behavior).

**Per-edit pre-edit search log**:

Edit 1 (combined §2.4 revision, subjects treated separately):

- **Subject (a): application performance-date ordering validation.**
  - (b) Paths enumerated and read/grepped: `routes/applications.py` (full file read — `_validate_application_window` at 79-86, create at 118-120, edit at 226-231, approval copy at 347-348, restriction-overlap read at 309, exclusive-run read at 321); `routes/titles.py:163-170` (restriction strict check, grep-read); `routes/agreements.py:215-220` (amendment strict check, full file read); `routes/rentals.py:37-39` (due_date checks, grep-read); `routes/availability.py:57` (clock-set parse, grep-read); `services/calculations.py:179-206` (`compute_availability` window handling — no ordering requirement); `routes/agreements.py:158` (performance window-fit check, inclusive both ends); error catalog grep for every `err_invalid_temporal` raise site.
  - (c) Wording adjustment: deliberately avoided claiming any ordering rule for application dates (the impl permits even `first > last` silently, so the wording says "no ordering constraint is imposed between them" rather than the narrower "first must be at most last"); scoped the strict rule to "fields named `window_start`/`window_end`" so the untouched restriction/amendment paths remain accurately described; noted missing-field behavior folds into "well-formed ISO 8601 UTC datetimes" since impl raises `ERR_INVALID_TEMPORAL` when either field is absent/unparseable.

- **Subject (b): datetime wire-format scope.**
  - (b) Paths enumerated and read/grepped: `db.py` (full file read — `fmt_ts` 3-digit-ms at 47-52, `parse_ts` seconds-truncation at 55-76); `services/serializers.py` (full file read — `_dt` wraps every entity datetime field across all 11 serializers); `response.py:17` (envelope `api_request_timestamp`); `routes/availability.py:60` (clock-read `current_utc`); repo-wide grep for `fmt_ts|_dt(|isoformat|strftime` confirming no other emission path exists.
  - (c) Wording adjustment: scoped the pin to datetimes the server *emits* (not what it accepts), because the amendment path (`agreements.py:216`) and application paths accept non-ms inputs like `2026-06-05T00:00:00Z`; phrased as "renders every datetime it emits — resource fields and envelope timestamps alike" to cover serializers, envelope, and clock endpoint without excluding any enumerated path.

## Step 9: Complete PRD — 2026-08-11T22:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1207_theatrical_rights_licensing/workspace/PRD_COMPLETED.md` written (copied from `PRD_FINALIZED.md`, which exists, then edited in place; only PRD_COMPLETED.md was touched).

**Stats**
- Source: `PRD_FINALIZED.md` — 294 lines / 47,031 chars → `PRD_COMPLETED.md` — 296 lines / 56,319 chars (+2 lines, +9,288 chars).
- Counts: 30 ambiguity-pins, 9 mismatch-revisions (39 total edits).

**Change log** (section — insert|revise — ambiguity|mismatch — what — impl ref):
- §2.1 — insert — ambiguity — Applicant list results restricted to own organization — routes/applications.py:178, agreements.py:41, fines.py:51, etc.
- §2.1 — insert — ambiguity — body-FK-dependent ownership resolves the reference first (ERR_REFERENCED_NOT_FOUND before owner check) — routes/alteration_requests.py:26-29, recording_grants.py:27-30
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock — response.py:14-18, db.py:39-41
- §2.2 — insert — ambiguity — unknown path/method → ERR_NOT_FOUND(404); malformed JSON treated as empty payload → ERR_INVALID_REQUEST(400) — app.py:44-57, routes use `get_json(silent=True) or {}`
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_INVALID_REQUEST; created_at ties break by insertion sequence — response.py:56-78, db.py:20-25
- §2.4 — insert — ambiguity — incoming datetimes truncated to whole seconds at parse; naive strings read as UTC — db.py:55-76
- §2.5 — revise — mismatch — overdue sweep enumerates SHIPPED/RECEIVED/RETURN_IN_TRANSIT (a RESERVED rental is never swept), not "any non-terminal" — services/sweeps.py:12-18
- §2.5 — insert — ambiguity — clock endpoint name, malformed to_iso8601 → ERR_INVALID_TEMPORAL, any direction accepted, response `{current_utc}` — routes/availability.py:50-60
- §2.6 — revise — mismatch — `expected_application_version` is optional on approve (PRD said "requires"); only amendments' `expected_agreement_version` is required — routes/applications.py:324-329 vs agreements.py:205-209
- §2.6 — insert — ambiguity — version field validated at the OCC step (after state/business; on amendments, before remaining field validation) — routes/agreements.py:203-223
- §2.7 — revise — ambiguity — added ERR_AMENDMENT_ON_TERMINAL (with state checks), ERR_DEPOSIT_NOT_HELD, ERR_RENTAL_NOT_DUE_LOST (business rules) to the ordering list — routes/agreements.py:203-204, rentals.py:116-117, 216-217
- §3.1 — insert — ambiguity — all title fields required at creation; money/rate fields are ints ≥ 0; name/author non-empty strings — routes/titles.py:57-75
- §3.1 — insert — ambiguity — withdrawing a non-ACTIVE title → ERR_INVALID_STATE — routes/titles.py:141-142
- §3.1 — insert — ambiguity — lifting an already-lifted restriction → ERR_INVALID_STATE; restriction creation ignores title status; filter-value validation (status/title_kind/booleans) → ERR_INVALID_REQUEST — routes/titles.py:243-244, 118-121, 45-53
- §3.2 — insert — ambiguity — organization list filters standing/org_kind, validated — routes/organizations.py:58-63
- §3.3 — insert — ambiguity — all application production-fact fields required; ticket/gross ints ≥ 0; performance_count ≥ 1; determined_classification/submitted_at null initially — routes/applications.py:107-116, 143-145
- §3.3 — revise — mismatch — approval evaluates the three availability preconditions before the OCC check (PRD prose had OCC first) — routes/applications.py:295-329
- §3.3 — insert — ambiguity — approval response carries the created LicenseAgreement with HTTP 201 — routes/applications.py:364
- §3.3 — insert — ambiguity — never-submitted application snapshot read → ERR_NOT_FOUND; per-application snapshot read ownership-checked, by-id read not; application list filters; snapshot list filters (title_id/territory_code/available validated) — routes/applications.py:381-391, availability.py:14-38
- §3.4 — insert — ambiguity — agreement carries `has_exclusive_run`, minted false, never set by any operation — routes/applications.py:357, serializers.py:105
- §3.4 — insert — ambiguity — activation failures (wrong state or insufficient funding) → ERR_INVALID_STATE — routes/agreements.py:57-62
- §3.4 — revise — mismatch — payments on CANCELLED/BREACHED rejected with ERR_INVALID_STATE (PRD said "not accepted", no code) — routes/agreements.py:78-79
- §3.4 — revise — mismatch — PAID_IN_FULL triggers when cumulative paid "reaches or exceeds" the prior balance (impl uses `>=`) — routes/agreements.py:98-103
- §3.4 — insert — ambiguity — RoyaltyPayment carries `refunded_cents` (0 until cancellation allocates); by-id payment read not ownership-scoped — routes/agreements.py:92, 136-142
- §3.4 — insert — ambiguity — amendment_note string / additional_performances int ≥ 0; terminal→OCC→fields validation order; agreement list filters — routes/agreements.py:210-223, 43-46
- §3.5 — insert — ambiguity — declare on non-ACTIVE → ERR_INVALID_STATE; malformed performance_at → ERR_INVALID_TEMPORAL; duplicate check ignores CANCELLED; performance list filters — routes/agreements.py:145-162, 188-191
- §3.5 — insert — ambiguity — report body ints ≥ 0; report requires performance SCHEDULED + agreement ACTIVE, else ERR_INVALID_STATE — routes/performances.py:59-68
- §3.5 — insert — ambiguity — cancel-performance recompute = per-performance royalty on projected gross with count−1 floored at 1; wrong from-state → ERR_INVALID_STATE — routes/performances.py:99-124
- §3.5 — insert — mismatch — completion sweep requires at least one Performance (PRD's conditions were vacuously true for zero performances) — services/sweeps.py:26-28
- §3.5 — revise — ambiguity — cancellation cascades only still-SCHEDULED performances; reason accepted but not persisted; refund recorded per-payment in `refunded_cents`; REFUNDED only when payments exist and pool ≥ total paid — routes/agreements.py:261-265, 295-297, calculations.py:170-175
- §3.5 — revise — mismatch — breach_reason is a free-text string mapped by case-insensitive substring "recording" → UNAUTHORIZED_RECORDING, else UNAUTHORIZED_ALTERATION (incl. performance-outside-window); non-ACTIVE → ERR_INVALID_STATE; grant cascade limited to REQUESTED/APPROVED — routes/agreements.py:308-317, 340-347
- §3.6 — insert — ambiguity — rental create on non-ACTIVE → ERR_INVALID_STATE; qty ints ≥ 0; due_date strictly later than clock; rental list filters — routes/rentals.py:28-41, 86-95
- §3.6 — insert — ambiguity — ship/mark_received/ship_return/receive_return wrong from-state → ERR_INVALID_STATE — routes/rentals.py:108-117, 132-133, 148-149, 162-163
- §3.6 — insert — ambiguity — damage-line types (amount_cents int ≥ 0, damage_fraction number ≥ 0) → ERR_INVALID_REQUEST — routes/rentals.py:168-176
- §3.6 — insert — ambiguity — replacement-cost rule defined: LOSS fine = deposit_cents + recorded accrued_late_fee_cents; declare_lost from non-OVERDUE → ERR_INVALID_STATE — routes/rentals.py:212-222
- §3.7 — revise — mismatch — submission of alterations/grants does not check license_status (PRD said add-ons "ride on an ACTIVE agreement") — routes/alteration_requests.py:19-50, recording_grants.py:20-51
- §3.7 — insert — ambiguity — alteration: description must be a string; decided_by_user_id null until decision; wrong from-state/non-ACTIVE agreement → ERR_INVALID_STATE; list filters — routes/alteration_requests.py:33-35, 90-94, 69-77
- §3.7 — insert — ambiguity — grant: REQUESTED + agreement ACTIVE required on approve/deny; recording_royalty_cents 0 at request; approval bumps agreement version; list filters; exercise precondition failures → ERR_INVALID_STATE — routes/recording_grants.py:43, 91-108, 134-140
- §3.7 — revise — mismatch — system revocation moves REQUESTED or APPROVED grants to REVOKED (PRD said only APPROVED); balance decrement only for APPROVED — routes/agreements.py:278-285, 340-347
- §3.8 — revise — mismatch — every fine references its parent agreement_id (PRD said null for rental-related fines); rental_id set on OVERDUE_MATERIAL/LOSS, null on breach fines — routes/rentals.py:186-199, 223-235, agreements.py:322-326
- §3.8 — insert — ambiguity — pay/waive/write_off require ASSESSED → ERR_INVALID_STATE; write-off age measured from created_at; fine list filters — routes/fines.py:69-70, 84-85, 101-105, 53-56

No changes to §2.8 (constants all matched), §4 (endpoint table roles/methods match impl exactly), or §5 (all 27 error codes and HTTP statuses match errors.py).


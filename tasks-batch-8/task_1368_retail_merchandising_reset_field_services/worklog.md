# Worklog — task_1368_retail_merchandising_reset_field_services

## Step 1: Create Task Directory — 2026-08-13T01:01:00.000Z

Task directory `tasks/task_1368_retail_merchandising_reset_field_services/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; treated as DONE per instructions (no index scan, no other task_* writes).

## Step 2: Generate Scaffold — 2026-08-13T01:38:30.000Z

All three artifacts are in place. Lint is clean.

---

## Summary

Generated the scaffold for `task_1368_retail_merchandising_reset_field_services` at `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key `scaffold_difficulty_design` (§1.8)
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key `scaffold_corner_design` (§1.9)

**Counts**
- Entities: 13 (Client, Project, Store, ProjectStore, FieldRep, Assignment, StoreVisit, PhotoEvidence, ExceptionReport, FixtureShipment, ReworkAuthorization, MileageLog, Invoice)
- State machines: 7 (Project, ProjectStore, Assignment, MileageLog, FixtureShipment, ReworkAuthorization, Invoice)
- Calculations: 6 (mileage_pay, travel_time_pay, visit_billing, invoice_total, rework_penalty, photo_window_check)
- Validations: 16 (priority-ordered)
- Endpoints: 60
- Errors: 18
- Roles: 6 (Anonymous, ProjectManager, FieldRep, Client, PayrollAdmin, BillingClerk)
- OCC concurrency rules: 2 (project-scope, invoice-finalize)
- Difficulty instances: 18 (2 per rule × 9 rules)
- Corner instances: 39 across all 9 sections of the claim-extraction guide

**Notable design decisions**
- **Archetype blend**: workflow-orchestration primary + pricing-engine secondary; layers optimistic-concurrency, cascading-side-effects, dual-variant-calculation, rate-threshold-triggers.
- **Difficulty breadth**: dual-variant calcs sit on different entity domains (FieldRep mileage pay vs Client visit billing); combinatorial formulas hit two different modes (tiered non-linear travel time vs per-line-then-sum invoice rounding with a 1-cent divergence pinned at 700+1750=2450 vs 2449); non-linear state machines live on different entities (ProjectStore rework cycle vs FixtureShipment exception loop); cascades originate from different triggers (verify → RECONCILING+invoice auto-create, depth 3; reject → REWORK_REQUIRED+ReworkAuthorization, depth 2); validation conflicts span different category pairs (state×business_fiscal, business_constraint×business_safety); boundary precision hits numeric threshold (score 20 → WATCH) and empty-intersection interval adjacency ([start,end) half-open); cross-entity dependencies cross different pairs (Assignment→ProjectStore, ReworkAuthorization→Project.posture); temporal overlap uses different interval semantics (scheduled-window intersection vs instantaneous ON_SITE occupancy); compensating invariants conserve different quantities (store-list cardinality vs billed cents).
- **1099 vs W-2 gating** encoded as a conditional validation (`ERR_CLASSIFICATION_FORBIDDEN` on FIXTURE_INSTALL) plus a tiered travel-time formula that zeroes out for C1099.
- **Logical clock** with the mandatory default `2026-08-01T00:00:00Z` and a clock-set endpoint that also drives the ReworkAuthorization expiry sweep.
- **OCC mechanics**: project-store creation increments parent `project.version`, making the stale-scope 412 reachable from DRAFT.
- Lint verdict: clean (`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5`, 769 calls scanned).

## Step 3: Copy Shared Files — 2026-08-13T01:39:10.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T01:44:30.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/workspace/PRD.md`.

**PRD line count:** 289 lines

**Section list:**
- §1 Introduction (3 paragraphs; business-context angle; logical-clock commitment with the pinned 2026-08-01T00:00:00Z start and `to_iso8601`/`current_utc` test-driving capability)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity translation (entity-backed `FieldRep`/`Client`, opaque `ProjectManager`/`PayrollAdmin`/`BillingClerk`/`Anonymous`); 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination (limit default 10, min 1, max 100, offset 0, `created_at` ascending, `meta` fields); 2.4 Common Resource Properties (incl. the `common_fields: false` carve-out for PhotoEvidence/ExceptionReport); 2.5 Nested Retrieval & Cross-Entity Ownership (left-to-right 404, five `ERR_CROSS_ENTITY_MISMATCH` scopes enumerated); 2.6 Validation Order (full priority cascade 1→16 stated in prose, including the rework-authorization check positioned after OCC); 2.7 Integer Cents & Pinned Rounding; 2.8 OCC (both rules: `expected_project_version`→`ERR_STALE_PROJECT_VERSION` 412, `expected_invoice_version`→`ERR_STALE_INVOICE_VERSION` 412); 2.9 Posture Ledger (all six penalty increments +10/+5/+7/+3/+5/+8, thresholds 20/40 with inclusive lower bounds); 2.10 Logical Clock & Temporal Rules
- §3 Business Logic (8 subsections, organized by lifecycle domain): 3.1 Clients/Stores/Workforce, 3.2 Project Setup (scope/cancel/auto-IN_FIELD), 3.3 Scheduling & Visit Execution (depart/check-in/check-out/cancel, fixture gating, double-booking half-open semantics, C1099 fixture ban), 3.4 Photo Evidence & Exceptions (ON_SITE-only uploads, inclusive capture window), 3.5 Verification/Rejection/Rework Loop (auto-authorization, client approve/deny, consumption, expiry sweep, store drop), 3.6 Fixture Shipments (all six scan transitions with penalties), 3.7 Billing (visit_billing PER_STORE/HOURLY variants, invoice totals, finalize cascade), 3.8 Mileage & Travel Pay (HOME_BASED/FIRST_STOP variants, three-tier W2-only travel pay with per-tier round-half-up)
- §4 Endpoint Definitions (status-code paragraph + 60-row table, 4 columns only; verified 1:1 against scaffold)
- §5 Error Code Catalogue (18 rows, 2 columns only; verified 1:1 against scaffold)

**Zero-Silence self-audit result:**
- Contract 1 (Field-Name Coverage): 65 required identifiers (entities[].fields + endpoint inputs + query params), 65 present in backticks, 0 missing — two passes run (first pass caught a code-fence extraction artifact in my audit script, not the PRD; second pass clean). **PASS**
- Contract 2 (Rule Coverage): all 16 validations with priority ordering expressed (§2.6 cascade + §3 trigger prose); both concurrency rules expressed with endpoint capability + occ field + exact error id/status; all 31 state-machine transitions across 7 machines expressed with preconditions paired to error ids and all side effects (including cross-entity cascades: project-store→project RECONCILING auto-invoice, reject→penalty+auto-authorization, drop→authorization expiry, store-row add→project version bump); all 6 calculations (mileage_pay, travel_time_pay, visit_billing, invoice_total, rework_penalty, photo_window_check) rendered as reconstruction-safe prose with constants embedded; all enum/state/default/structured field content placed; sibling branches (three drop branches, two cancel branches, six scan branches, two mileage variants) rendered with equal density. **PASS**
- Contract 3 (§3 Path Purity): 397 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**
- Additional checks: no fuzzy/approximating words; no operator syntax anywhere in prose (the one `==` in a §4 description cell copied from the scaffold was rewritten as plain prose); all 18 error IDs, all state/enum values, and all 6 role names present verbatim.

## Step 5: Generate Unit Tests — 2026-08-13T02:05:00.000Z

Generation complete. Summary:

## Test counts

**Queue A (Difficulty): 34 tests** — 17 of 18 instances × 2 tests each, all tagged `Design: Difficulty/<rule_id>/<instance>`.

**Queue B (Corner): 39 tests** — 39 of 39 non-stub instances × 1 test each (the file contains zero `excluded_because:` stubs), all tagged `Design: Corner/<section>/<instance>`.

**Total: 73 tests** across 9 files (`test_01` entities/listing … `test_09` posture/cancellation/invariants).

## Skipped instances (1, with reason)

- `Difficulty/priority_pair_validation_conflict/fixtures_gating_vs_classification_on_assignment_create` — the instance asserts `ERR_REP_DOUBLE_BOOKED` masks `ERR_CLASSIFICATION_FORBIDDEN` "because priority 7 precedes 12", but PRD §2.6 collapses both into a single "Seventh, the domain business constraints" tier with no intra-tier ordering. Two PRD-only readers could order these checks either way, so the asserted outcome is not uniquely derivable (validation-priority silence pattern). Each rule remains tested in isolation via the corner instances `classification_forbidden_on_fixture_install` and `fixture_checkin_blocked_until_delivered`.

## Notable adjudications / recipe repairs

- `rep_single_on_site_occupancy` (negative test only): PRD §3.3 says the check-in rejection is "a double-booking violation" without naming an error id, while the state-machine framing implies `ERR_INVALID_STATE` — asserted via the sanctioned `validate_error_is_one_of([ERR_REP_DOUBLE_BOOKED, ERR_INVALID_STATE])` (both 409).
- `cross_entity_mismatch_assignment_project_store`: recipe scoped proj_2 with zero store rows, which PRD §3.2 forbids; repaired by giving proj_2 its own store row so the trigger actually reaches the cross-entity check.
- Photo-window clock repair baked into the `execute_visit` fixture: recipes uploaded photos with `captured_at` ahead of the logical clock (PRD §3.4 rejects future timestamps); the fixture drives the clock so BEFORE lands exactly at `check_in_at` and AFTER exactly at the check-out instant.
- `client_create_success_and_defaults`: dropped the `version == 1` sub-assertion (PRD §2.4 pins only +1-per-mutation, not the initial value); retained ACTIVE status, bare-UUID id, and ISO-8601 timestamp assertions.
- All OCC scope calls re-read the current project version instead of assuming a literal initial version.

## Helper files created (`test_helpers/`)

`types.py` (12 entities; PhotoEvidence/ExceptionReport correctly omit `updated_at`/`version`), `api_client.py` (44 methods, one per PRD §4 endpoint incl. `/_clock/set_current_utc`), `api_errors.py` (18 error ids + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + posture invariant), `factories.py`, `constants.py` (penalty increments, posture thresholds, tier constants), `test_users.py` (opaque role constants + `make_field_rep_headers`/`make_client_headers` builders, used throughout for ownership-gated calls), `fixtures.py` (clock-driven `execute_visit`, `make_scenario`, `visit_store`, `complete_rework_loop`, `setup_reconciling_project`, invoice helpers), `__init__.py` barrel.

## Stage 2 self-audit

- **Tag coverage (programmatic, against both yamls):** 56 distinct tags / 73 tests; every translated difficulty instance has exactly 2 tests; every corner instance exactly 1; no untagged, dual-tagged, or dangling tags; tag is always the docstring's last line.
- **Forbidden-pattern scan:** no `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold"/table references in generated code.
- **Citations:** all 73 docstrings' PRD quotes survive a verbatim ≥8-word-window grep of `PRD.md`.
- **Sanity:** all files `py_compile` clean; `pytest --collect-only` discovers 73 tests with zero import errors.

## Step 6: Generate Implementation — 2026-08-13T02:05:00.000Z

All checks pass. Summary of the delivered implementation:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/workspace/implementation/`)

- `start.sh` — guarded dependency install (no-op once Flask present) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry, blueprint registration under `/retail-reset` + `/_clock`, envelope-compliant error handlers (404/405/500)
- `db.py` — in-memory dict stores (empty at boot, zero seeding), logical clock defaulting to `2026-08-01T00:00:00Z`, UUID ids, `version`/`updated_at` touch helpers, 3-fractional-digit ISO timestamps
- `errors.py` — all 18 catalog error IDs with exact HTTP statuses
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination meta (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5 declared roles, typed field validators, ISO datetime/date parsers
- `services.py` — all calculations: mileage (HOME_BASED/FIRST_STOP variants), tiered travel pay (per-tier round-half-up via `Decimal`, C1099 always 0), visit billing (PER_STORE flat / HOURLY prorated round-half-up, rework = 0), invoice totals (integer sum, never re-rounded), rework-penalty posture thresholds (20/40, inclusive lower bounds), RECONCILING cascade with auto-invoice, clock-driven rework expiry sweep (+7), fixture depart/check-in gates
- `routes/` — 13 modules: clients, stores, reps, projects, project_stores, assignments, store_visits, exceptions, rework, shipments, mileage, invoices, clock

## Endpoint count
60 API routes registered (59 under `/retail-reset` + `POST /_clock/set_current_utc`), matching the scaffold endpoint table exactly.

## Key semantics implemented
- Validation cascade in scaffold priority order (auth → RBAC → existence L-to-R → state → cross-entity → temporal → business constraints → input sanitization → OCC → rework-authorization check last)
- OCC: `expected_project_version` on scope (412 `ERR_STALE_PROJECT_VERSION`), `expected_invoice_version` on finalize (412); store-list add/drop bumps parent project version
- Full state machines: Project (incl. IN_FIELD cancel guards and cascade drops), ProjectStore, Assignment, StoreVisit verify/reject cascades, MileageLog, FixtureShipment scan map, ReworkAuthorization (CONSUMED/EXPIRED), Invoice
- Entity-backed ownership 403s (rep on own assignments/logs, client on own projects) and role-scoped lists

## Verification
`bash start.sh` boots cleanly and serves within ~2s. Three smoke suites (26 assertions) passed covering: full happy path through invoice finalization, OCC 412s, double-booking 409 with adjacency allowed, rework loop (reject → REQUESTED → client approve → CONSUMED → 0-billed rework visit), drop cascade to RECONCILING, C1099/W2 pay anchors (150-min W2 day = 5940 cents), fixture gates (`ERR_FIXTURES_NOT_DELIVERED`), scan penalties (+3/+5/+8), posture WATCH/ESCALATED with client-approval block, expiry sweep, duplicate-invoice guard, auth 401/403, pagination validation, and a reboot test confirming the store resets to empty (in-memory only, no persistence).

## Step 7: Run Tests and Iterate — 2026-08-13T02:25:00.000Z

All 8 rounds of the stability sweep pass 73/73. Exit criterion met.

## Summary

**Iterations run: 2** (iteration 1: 5 distinct failing tests in the union + 1 flaky infra failure; iteration 2: all 8 rounds clean, 73/73 × 8)

**Tests deleted: none.** Every failing test traced to a verbatim PRD rule with unique derivability; all fixes were faithfulness corrections, not deletions.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/test_helpers/fixtures.py` — `make_scenario()`: the `scope_type` parameter was accepted but silently dropped (project always created with factory default `AUDIT`). Now forwarded into project creation (`{"scope_type": scope_type, **project_overrides}`). This single fixture bug caused two consistent failures: `test_c1099_on_fixture_install_forbidden` (PRD 3.3 `ERR_CLASSIFICATION_FORBIDDEN` — the C1099-on-FIXTURE_INSTALL precondition was never constructed, so the PRD-required check correctly never fired) and `test_checkin_blocked_until_fixtures_delivered` (PRD 3.3 `ERR_FIXTURES_NOT_DELIVERED` — same missing FIXTURE_INSTALL precondition disabled the delivery gate). Classic fixture-masquerading-as-implementation-bug pattern.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/test_suite/test_04_visit_execution_and_photos.py` — `test_photo_before_checkin_rejected`: the guard assertion compared ISO timestamps as raw strings (`visit["check_in_at"] >= "2026-08-05T09:30:00Z"`), which fails because the server stamps `check_in_at` with three fractional digits per PRD 2.2 and `".000Z" < "Z"` lexicographically. Replaced with parsed-datetime comparison. The actual rule under test (PRD 3.4 `ERR_TEMPORAL_INVALID` on pre-check-in capture) was and remains asserted unchanged.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/workspace/implementation/start.sh` — eliminated the double python/flask import per boot (dependency check now runs in the same interpreter that runs `app.py` via `runpy`, preserving install-if-missing semantics). Boot time 0.755s → 0.376s. This shrinks the 15s restart-poll failure window that produced the flaky infrastructure errors ("API server could not be restarted") at random early tests when the 8 concurrent rounds overlapped other host load. No application logic was touched — no endpoint, field, or check was added or removed; all PRD-required validations remain in place.

## Step 8: Finalize PRD — 2026-08-13T02:35:00.000Z

Done. `PRD_FINALIZED.md` produced with exactly one inline insertion; everything else verbatim.

**Line counts / %-delta:** PRD.md 289 lines / 43,234 bytes → PRD_FINALIZED.md 289 lines / 43,378 bytes. Delta: 0 lines (0.0%), +144 bytes (+0.33%).

**Changes:**
- §2.10 (The Logical Clock and Temporal Rules) — insert — appended "Every server-stamped timestamp is serialized as ISO 8601 in UTC with exactly three fractional digits (for example, `2026-08-05T09:30:00.000Z`)." after the first sentence — `implementation/db.py:58-61` (`fmt_ts`, the single formatter used by every stamping site).

**Step 7 items that produced no edit (with reason):**
- `test_helpers/fixtures.py` `scope_type` drop — pure fixture bug. PRD §3.3 already uniquely determines both affected rules: `ERR_CLASSIFICATION_FORBIDDEN` matches `implementation/routes/assignments.py:104-107` verbatim, and the `ERR_FIXTURES_NOT_DELIVERED` depart/check-in gates match `implementation/services.py:230-253` verbatim (FIXTURE_INSTALL-only; depart gate date-conditioned; check-in gate on LABEL_CREATED/IN_TRANSIT/DELIVERY_EXCEPTION).
- `implementation/start.sh` single-interpreter boot — pure infrastructure (boot-time optimization); no endpoint, field, or check changed; PRD does not constrain boot internals.

**Per-edit pre-edit search log:**
- Edit 1 (§2.10 timestamp serialization):
  - (a) Subject: string serialization format of server-stamped/server-generated timestamps.
  - (b) Paths enumerated and read/grepped (`fmt_ts|isoformat|strftime|check_in_at|check_out_at` and `db.now()|datetime.now|_clock_now` over all implementation `*.py`): `db.py:58-61` (formatter definition), `db.py:64-73` (`base_fields` → `created_at`/`updated_at` on all 11 primary resources), `db.py:76-82` (`light_fields` → photo/exception `created_at`), `db.py:85-88` (`touch` → `updated_at`), `response.py:21` (envelope `api_request_timestamp`), `routes/clock.py:21` (`current_utc`), `routes/assignments.py:240,244` (`check_in_at`), `routes/assignments.py:275-277` (`check_out_at`); read-only clock consumers confirmed non-stamping: `store_visits.py:85-95`, `shipments.py:126-128`, `project_stores.py:44`, `services.py:205,236`. Client-supplied fields stored verbatim (must stay outside the claim): `captured_at` (`store_visits.py:106`), `scheduled_start`/`scheduled_end` (`assignments.py:134-135`), `promised_date` (`shipments.py:67`), `due_date`.
  - (c) Wording adjustment: scoped to "server-stamped timestamp" (the section's existing term) rather than "all timestamps" so verbatim-stored client-supplied fields are not mis-described; specified "exactly three fractional digits" to cover the always-padded `.000Z` case `fmt_ts` emits, which is the exact behavior the Step 7 test fix turned on. Consistent with §2.2 (`api_request_timestamp`, already three-fractional-digit) and §2.4 (`created_at`, already pinned; `updated_at` now covered and matches `touch`).

File: `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-13T02:52:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1368_retail_merchandising_reset_field_services/workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Source vs output:** PRD_FINALIZED.md 289 lines / 43,378 chars → PRD_COMPLETED.md 291 lines / 49,060 chars (char delta +5,682). All edits are inline inserts/revisions; no new sections.

**Counts:** 21 ambiguity-pins, 5 mismatch-revisions (26 changes total; the two `due_date` fixes are one logical mismatch fixed in two sections).

**Changes:**
- §1 — insert — ambiguity — clock-set accepts any ISO 8601 instant; monotonic increase not enforced — implementation/routes/clock.py:18-19
- §2.2 — revise — ambiguity — `api_request_timestamp` taken from wall-clock time, not the logical clock — implementation/response.py:21
- §2.2 — insert — ambiguity — unexpected server fault surfaces as `ERR_INTERNAL` (HTTP 500) in the same envelope — implementation/app.py:44-48
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — implementation/response.py:46-65
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — implementation/db.py:64-73
- §2.5 — revise — mismatch — cross-entity guard list expanded five → seven operations (adds fixture-shipment registration, invoice creation) and adds RA-must-match-project-and-store / rejected-visit-belongs-to-store clauses — implementation/routes/assignments.py:83-87, rework.py:51-58, shipments.py:46-48, invoices.py:38-40
- §2.6 — insert — ambiguity — entity-ownership (403) checks evaluated immediately after target existence, ahead of state legality — implementation/routes/store_visits.py:74-84, mileage.py:46-48
- §2.10 — revise — ambiguity — entity `created_at`/`updated_at` also stamped from the logical clock — implementation/db.py:58-88
- §2.10 — revise — mismatch — `due_date` anchor is the current logical date, not "the project's scope date" — implementation/routes/project_stores.py:42-45
- §3.1 — insert — ambiguity — no endpoint changes client status; `SUSPENDED`/`TERMINATED` reserved, clients stay `ACTIVE` — implementation/routes/clients.py (no status route)
- §3.1 — revise — mismatch — `store_number` carries no system-enforced uniqueness; only the §3.2 store-list duplicate rule exists — implementation/routes/stores.py:12-25
- §3.1 — insert — ambiguity — no endpoint changes rep status; reps stay `ACTIVE` — implementation/routes/reps.py (no status route)
- §3.2 — insert — ambiguity — store rows addable while project is `DRAFT`/`SCOPED`/`IN_FIELD`; `RECONCILING`/`COMPLETED`/`CANCELLED` → `ERR_INVALID_STATE` — implementation/routes/project_stores.py:38-40
- §3.2 — revise — mismatch — `due_date`-before-scope-date rule re-anchored to current logical date — implementation/routes/project_stores.py:44-45
- §3.2 — insert — ambiguity — scoping precondition failures (not `DRAFT`, no `PENDING` rows, client not `ACTIVE`) are `ERR_INVALID_STATE` (409) — implementation/routes/projects.py:111-118
- §3.2 — insert — ambiguity — project cancellation does not retire open rework authorizations; only the clock sweep expires them — implementation/routes/projects.py:139-167
- §3.3 — revise — ambiguity — all assignment-creation precondition violations (not just the live-assignment one) are `ERR_INVALID_STATE`; scheduling on a `REWORK_REQUIRED` row without `rework_authorization_id` is also `ERR_INVALID_STATE` — implementation/routes/assignments.py:65-78
- §3.3 — revise — ambiguity — checkout computes `on_site_minutes` as whole minutes rounded down and returns the updated store-visit record — implementation/routes/assignments.py:275-285
- §3.4 — insert — ambiguity — exception filing is not gated on visit/assignment state — implementation/routes/store_visits.py:127-148
- §3.5 — revise — ambiguity — verification additionally requires the assignment to be `SUBMITTED` — implementation/routes/store_visits.py:181-182
- §3.5 — revise — mismatch — rejection requires assignment `SUBMITTED` too (PRD said "only … `PENDING_REVIEW`") — implementation/routes/store_visits.py:211-214
- §3.5 — insert — ambiguity — auto-created rework authorization carries `reason` unset — implementation/routes/store_visits.py:224-233
- §3.5 — insert — ambiguity — manual rework-authorization creation has no state preconditions on project/row/visit — implementation/routes/rework.py:51-76
- §3.5 — revise — ambiguity — RECONCILING auto-invoice created when no *live* (`OPEN`/`FINALIZED`) invoice exists — implementation/services.py:183-184
- §3.5 — insert — ambiguity — drop expires open authorizations without the +7 penalty, increments the parent project's `version`, and can trigger the `RECONCILING` cascade — implementation/routes/project_stores.py:119-135
- §3.6 — insert — ambiguity — `scan_result` enum pinned to `IN_TRANSIT`/`EXCEPTION`/`DELIVERED`/`LOST`; bad value → 400, illegal transition → 409 — implementation/routes/shipments.py:12-18, 108-119
- §3.7 — insert — ambiguity — manual invoice creation imposes no project-state precondition — implementation/routes/invoices.py:20-51
- §3.7 — insert — ambiguity — finalize omitting `adjustment_cents` retains the invoice's existing adjustment — implementation/routes/invoices.py:103-104
- §3.8 — revise — ambiguity — mileage log submitted before assignment reaches `SUBMITTED`/`VERIFIED` is refused with `ERR_INVALID_STATE`; log is born with pay amounts already computed — implementation/routes/mileage.py:49-51, 60-72
- §4 — insert — ambiguity — pins role-scoped list visibility, parent-chain read ownership (incl. that any FieldRep may read stores/project-store rows/shipments), and the exact-match query filters per list endpoint — implementation/routes/*.py list/get handlers
- §5 — insert — ambiguity — adds `ERR_INTERNAL` | 500 row to the error catalogue — implementation/app.py:44-48

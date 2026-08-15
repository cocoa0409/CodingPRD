# Worklog — task_1552_aircraft_component_mro_overhaul_shop

## Step 1: Create Task Directory — 2026-08-13T20:32:00.000Z

Task directory `tasks/task_1552_aircraft_component_mro_overhaul_shop/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per orchestration instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T21:50:00.000Z

All three scaffold artifacts are written and pass a clean lint.

## Output files

- `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Inventory

| Metric | Count |
|---|---|
| Entities | 16 (Customer, PartCatalogEntry, DirectiveRecord, ComponentUnit, WorkOrder, DiscrepancyCard, DirectiveCompliance, PartsRequisition, TestCell, TestCellBooking, ReleaseCertificate, ExchangeAgreement, LeaseAgreement, WarrantyClaim, Invoice, TraceabilityRecord) |
| State machines | 10 (cyclic WorkOrder retest loop + quote self-loop, cyclic/forking PartsRequisition, parallel condition×custody dimensions on ComponentUnit, plus 7 smaller machines) |
| Calculations | 8 (tat_penalty ADJUSTED/CALENDAR variants, per-line-rounded invoice total, pinned-order exchange settlement, FULL/PRORATED warranty credit, inclusive BER threshold, lease accrual with 1.5x overage, deterministic pool selector, credit-exposure ledger) |
| Validations | 26 priority-ordered rows |
| Endpoints | 60 (34 POST actions + 26 GETs incl. all FK reverse-reachability and `POST /mro/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`) |
| Errors | 42 |
| Roles | 6 (segregation_of_duties model: Inspector ≠ WorkOrder.technician_user_id; Customer is `entity_backed:Customer`) |
| §1.8 difficulty instances (non-stub) | 21 (rules 1–9: 2/3/3/2/2/3/2/2/2) |
| §1.9 corner instances (non-stub) | 48 live + 3 `excluded_because` stubs = 51 total |

## Difficulty highlights (beyond-expert design)

- **Dual-variant calcs on different domains**: TAT penalty (Invoice) ADJUSTED-vs-CALENDAR producing 170000 vs 470000 on identical timestamps; warranty FULL-vs-PRORATED (2575000 vs 800000).
- **Combinatorial modes (a)+(b)+(c)**: 5-input max/min/cap TAT formula; pinned per-line rounding (parts 83332 vs 83333 sum-then-round); circular-looking exchange settlement with pinned (1)→(5) evaluation order (BER core 3 days late → exactly 8175000).
- **Cascades**: depth-4 core-return chain (unit induction → settlement invoice → exposure debit → agreement close) and depth-3 warranty-accept chain (claim → rework WorkOrder spawned mid-pipeline → unit re-induction + trace).
- **Two true-race OCC rules** (quote-approval on WorkOrder.version after re-quote supersede; lease-create on ComponentUnit.version with legal forward bookings) — both lint-verified as `${var}`-driven 412s.
- **Two interval semantics**: half-open test-cell windows (adjacency allowed) vs day-closed lease intervals (shared boundary day conflicts).
- **Compensating invariants**: pool_depth + open exchange obligations conserved across fulfill/core-return; customer exposure conserved across invoice issue/pay.

## Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (733 calls scanned)
- Additional scripted audits passed: instance-name uniqueness across both design files, all `grounds` resolve to declared §1.1–§1.7 elements, all 42 errors exercised by at least one live instance, enum closure (dropped unproduced Customer.SUSPENDED), no forbidden concurrency vocabulary, and a booking-window/clock replay pass (which caught and fixed one half-open boundary bug in the TAT cap-binding corner).

## Step 3: Copy Shared Files — 2026-08-13T21:51:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1552_aircraft_component_mro_overhaul_shop/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T22:12:00.000Z

Generation complete. All audits pass.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/workspace/PRD.md` — 382 lines.

**Section list:**
- §1 Introduction (2 paragraphs — regulatory + commercial framing, `/mro` mount)
- §2 Global Specifications: 2.1 RBAC (6 roles, identity prose per role), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties (incl. the `common_fields: false` trio DirectiveRecord/ReleaseCertificate/TraceabilityRecord), 2.5 The Logical Clock (startup default `2026-08-01T00:00:00Z`, sweep trigger), 2.6 Monetary Precision and Per-Line Rounding, 2.7 Optimistic Concurrency Control (both OCC rules, `ERR_STALE_VERSION` 412), 2.8 Resource Existence and Nested Path Validation (8 family 404s), 2.9 Validation Pipeline and Check Ordering (6-stage pipeline + 12 endpoint-specific orderings), 2.10 Customer Credit Exposure and Credit Holds (inclusive boundary invariant), 2.11 Back-to-Birth Traceability (11-event vocabulary)
- §3 Business Logic (9 subsections): 3.1 Commercial Onboarding, 3.2 Unit Registration and Induction, 3.3 Teardown and Quoting Cycle (incl. BER evaluation + re-quote self-loop), 3.4 Repair/Directive Compliance/Parts Sourcing (OEM/PMA fork-join, markup tiers), 3.5 Test Cells/ATP/8130 Release (segregation of duties, retest cycle), 3.6 Invoicing/TAT Penalty/Payment (ADJUSTED vs CALENDAR variants), 3.7 Rotable Exchange Pool (selector, 4-hop core-return cascade, default sweep), 3.8 Lease Agreements (day-closed overlap, 1.5x overage), 3.9 Warranty Claims and Rework (FULL/PRORATED credit, 3-hop accept cascade)
- §4 Endpoint Definitions — 60 rows (matches scaffold's 60 endpoints), 4 columns only
- §5 Error Code Catalogue — 42 rows (matches scaffold's 42 errors), 2 columns only

**Zero-Silence self-audit (§1.1–§1.7 trace):**
- §1.1 Entities: all 108 field names across 16 entities present verbatim in backticks → PASS
- §1.2 State machines: all 43 transitions across 11 machines expressed in prose (from/to states, preconditions paired with error IDs, side effects, cascade hops); all 34 clean state values and 29 enum values present → PASS
- §1.2.1 Concurrency: both OCC rules expressed with write operation, `expected_work_order_version` / `expected_unit_version`, `ERR_STALE_VERSION` (412), no race framing → PASS
- §1.3 Calculations: all 8 (tat_penalty, invoice_total, exchange_settlement, warranty_credit, ber_evaluation, lease_accrual, pool_unit_selector, credit_exposure) rendered as precise prose — pinned per-line rounding, pinned 5-step settlement order, inclusive boundaries, embedded constants ($1,000/$10,000 markup tiers, $250.00 admin fee, $500.00/day late fee, 80% BER core charge, 65% default BER threshold, 15-day core window, 5 grace days, 1.5x overage multiplier) → PASS
- §1.4 Validations: global priority pipeline plus explicit per-endpoint orderings (quote: safety before fiscal; release: state before safety; OCC before business logic; etc.) → PASS
- §1.5 Endpoints: all 60 in §4 with methods, paths, authorized roles; 201/200 status rules stated → PASS
- §1.6 Errors: all 42 IDs with correct HTTP statuses in §5; every ID also mentioned with its trigger in §2/§3 prose → PASS
- §1.7 Roles: all 6 role names exact; opaque vs entity-backed identity prose per role → PASS

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): entity fields 108/108, request inputs 67/67, query params 17/17, path params 12/12 (inside §4 path tokens), 0 missing → **PASS**
- Contract 2 (Rule Coverage): priority orderings 12 endpoint groups expressed; 2/2 OCC rejections; 43/43 transitions; 8/8 calculations; all validation conditions matchable to error IDs; all endpoint side effects expressed; sibling branches symmetric (PASS/FAIL, ACCEPT/DENY, RETURN_UNREPAIRED/SCRAP, BER/NON_BER, FULL/PRORATED, ADJUSTED/CALENDAR) → **PASS**
- Contract 3 (§3 Path Purity): 631 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos → **PASS**

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## RESUME ASSESSMENT — 2026-08-13T22:50:11.000Z

The previous run was killed mid-flight after Step 4's worklog entry. Resume audit findings:

- **Steps 1–4**: complete and valid (entries above; all artifacts verified on disk).
- **Step 5 (unit tests)**: PARTIAL — killed mid-generation, no worklog entry was recorded. Existing artifacts are internally valid: `test_helpers/` has all 9 expected files; `test_suite/` has conftest + test_01–test_06 = 67 test functions; every file py_compiles; every test carries exactly one `Design:` tag and all 67 tags resolve to real §1.8/§1.9 instances (0 bad, 0 dual, 0 untagged). However coverage stops mid-design: 48 of 69 live non-stub instances are covered (difficulty 20/21 across all 9 rules; corner 28/48). The 21 uncovered live instances cluster in the design's tail sections (validations 9/11 missing, rbac 0/3, endpoints 0/2, errors 1/2, consistency 0/1, state_machines 3 missing, calculations 1 missing, difficulty compensating_invariant 1 missing) — categories whose rules ARE verbatim-covered in PRD §2.1/§2.2/§2.8, so they would not have failed the PRD-first skip filter. Verdict: coverage truncation, not deliberate skips. Action: a Step 5 completion subagent will emit tests for the 21 uncovered instances as NEW files (test_07+), leaving the existing 6 valid files untouched.
- **Step 6 (implementation)**: complete and valid — 60/60 scaffold endpoints registered across 11 blueprints, app.py/start.sh/requirements.txt present and executable, py_compiles clean, boots fresh and serves the correct error envelope with the logical clock default `2026-08-01T00:00:00Z` (orchestrator smoke test, PORT=19877). Reused as-is.
- **Steps 7–9**: never started (no results.*.json files exist).

## Step 5: Generate Unit Tests — 2026-08-13T23:07:16.000Z

The original Step 5 subagent was killed mid-flight before returning a summary (see RESUME ASSESSMENT above). Its on-disk output was verified valid and retained: `test_helpers/` (9 files: __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py) and `test_suite/` (conftest.py + test_01–test_06 = 67 tests, 67 valid Design tags, 48/69 live instances covered). A completion subagent then generated the 21 missing tests. Verbatim summary of the completion subagent:

## Summary

Generated 21 new tests covering exactly the 21 uncovered live design instances, as three NEW files. No pre-existing file was modified (test_01–06, conftest.py, test_helpers/ all retain original mtimes; `python3 -m py_compile` passes on all three new files; every import verified resolvable against `test_helpers`).

### `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_suite/test_07_validations.py` (9 tests)
- `test_fulfill_blocked_by_credit_hold` → `Corner/validations/fulfill_blocked_by_credit_hold`
- `test_create_customer_missing_auth_header_returns_400` → `Corner/validations/create_customer_missing_auth_header_returns_400`
- `test_wo_create_unit_owner_mismatch` → `Corner/validations/wo_create_unit_owner_mismatch`
- `test_core_return_part_mismatch` → `Corner/validations/core_return_part_mismatch`
- `test_pma_approval_by_non_owner_customer_forbidden` → `Corner/validations/pma_approval_by_non_owner_customer_forbidden`
- `test_payment_wrong_amount_then_double_pay_rejected` → `Corner/validations/payment_wrong_amount_then_double_pay_rejected`
- `test_booking_overlap_precedes_ata_capability` → `Corner/validations/booking_overlap_precedes_ata_capability`
- `test_segregation_of_duties_blocks_self_inspection` → `Corner/validations/segregation_of_duties_blocks_self_inspection`
- `test_wo_create_unit_not_off_site_rejected` → `Corner/validations/wo_create_unit_not_off_site_rejected`

### `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_suite/test_08_state_and_calc_gaps.py` (5 tests)
- `test_claim_denied_terminal_then_review_rejected` → `Corner/state_machines/claim_denied_terminal_then_review_rejected`
- `test_invoice_double_generate_rejected` → `Corner/state_machines/invoice_double_generate_rejected`
- `test_rework_close_bubbles_claim_to_settled` → `Corner/state_machines/rework_close_bubbles_claim_to_settled`
- `test_warranty_limits_exceeded_rejected` → `Corner/calculations/warranty_limits_exceeded_rejected`
- `test_customer_exposure_conserved_across_issue_and_pay` → `Difficulty/compensating_invariant/customer_exposure_conserved_across_issue_and_pay`

### `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_suite/test_09_rbac_endpoints_errors_consistency.py` (7 tests)
- `test_technician_cannot_create_customer` → `Corner/rbac/technician_cannot_create_customer`
- `test_inspector_cannot_create_work_order` → `Corner/rbac/inspector_cannot_create_work_order`
- `test_customer_cannot_review_claim` → `Corner/rbac/customer_cannot_review_claim`
- `test_response_envelope_object_and_error_shapes` → `Corner/endpoints/response_envelope_object_and_error_shapes`
- `test_work_order_version_increments_visible_via_get` → `Corner/endpoints/work_order_version_increments_visible_via_get`
- `test_not_found_sweep_returns_404s` → `Corner/errors/not_found_sweep_returns_404s`
- `test_immediate_consistency_release_response` → `Corner/consistency/immediate_consistency_release_response`

**Instances skipped:** none. All 21 passed the PRD-first two-condition filter — every asserted rule (error_id, HTTP status, ordering, and literal values) is named in verbatim PRD.md prose (each citation was grep-verified against PRD.md before emission), and every expected outcome is uniquely derivable by a PRD-only reader. The 3 `excluded_because:` corner stubs stay excluded.

**Untranslatable instances:** none.

Notable derivability decisions:
- `test_rework_close_bubbles_claim_to_settled` asserts only `warranty_credit_applied_cents == 2575000`, `total_cents == 0`, `penalty_variant == "NONE"`, and the `SETTLED` bubble-up. The rework order's `labor_charge_cents` is not PRD-pinned (rework skips quote), but the floored total is 0 under every PRD-consistent reading since the credit (2575000) exceeds the maximum possible charges (2400000) — so the assertions are ambiguity-proof.
- `test_work_order_version_increments_visible_via_get` asserts v1→v4 == 1→4, consistent with the already-covered `Corner/entities/customer_creation_defaults_and_system_fields` precedent that creation yields `version == 1`, plus §2.4's "increments by exactly 1 on every mutation".
- `booking_overlap_precedes_ata_capability` relies on §2.9's explicit booking check order (from-state → overlap → ATA), so the two-trigger assertion is PRD-derivable.

Orchestrator verification after completion: all 9 test files py_compile; 88 test functions total, 88 Design tags (1:1); live-instance coverage now 69/69 (difficulty 21/21, corner 48/48).

## Step 6: Generate Implementation — 2026-08-13T23:07:16.000Z

The original Step 6 subagent was killed before returning a summary (see RESUME ASSESSMENT above), but its on-disk output was verified complete and valid by the orchestrator and is reused as-is: `workspace/implementation/` with app.py (Flask app factory + error handlers), db.py (in-memory storage), errors.py, response.py, middleware.py, helpers.py, requirements.txt (flask>=3.0,<4.0), executable start.sh (PORT-aware, binds 0.0.0.0, foreground exec, conditional pip install), and routes/ with 11 blueprints (customers, catalog, units, work_orders, requisitions, test_cells, exchange, lease, warranty, invoices, clock_api) registering exactly 60 routes — matching the scaffold's 60 endpoints. All files py_compile clean; orchestrator smoke test (fresh boot on PORT=19877) served the correct error envelope (`data.error_id`/`meta.api_request_id`/`response_type:"error"`) with the logical clock defaulting to `2026-08-01T00:00:00Z`. Storage is in-memory only (Python dicts), no seeding.

## Step 7: Run Tests and Iterate — 2026-08-13T23:18:51.000Z

All 8 rounds passed 88/88. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (sweep 1: 85/88 in all 8 rounds with the same 3 failures; fix applied; sweep 2: 88/88 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_helpers/assertions.py` — added `parse_instant(value)` helper that parses an ISO 8601 UTC timestamp into an aware datetime for instant comparison. Why: PRD §2.4/§2.2 pin the "three fractional digits" serialization only for `created_at`/`updated_at`/`api_request_timestamp`; §2.5 lists `received_at`/`released_at`/`promised_return_at` as clock-stamped but is silent on their string format (and writes the clock instant itself without fractional digits), so exact-string equality on those fields is not uniquely derivable by a PRD-only reader (two-reader divergence: `...T04:00:00Z` vs `...T04:00:00.000Z`).

- **Fixes applied to `test_suite/` (STEP 1c partial-coverage correction — kept the covered instant assertion, removed the uncovered serialization-format pinning):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_suite/test_09_rbac_endpoints_errors_consistency.py` — `test_work_order_version_increments_visible_via_get`: `received_at` and `promised_return_at` assertions now compare parsed instants (PRD §2.5 clock default + §3.3 `received_at + contract_tat_hours` remain fully asserted); `test_immediate_consistency_release_response`: `released_at` assertion now compares parsed instant (PRD §3.5 "stamps `released_at` with the clock" remains fully asserted).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1552_aircraft_component_mro_overhaul_shop/test_suite/test_04_invoice_calculations.py` — `test_tat_penalty_five_input_max_min_cap_formula`: `promised_return_at` assertion now compares parsed instant. All money/penalty assertions in that test were already passing and are untouched.

- **Fixes applied to `implementation/`:** none — the implementation's uniform three-fractional-digit timestamp serialization is a faithful PRD reading; the bug was over-specified string-literal assertions in the tests.

## Step 8: Finalize PRD — 2026-08-13T23:23:46.000Z

Done. `PRD_FINALIZED.md` is written with exactly one in-place sentence appended to §2.5; the diff against `PRD.md` is that single line.

## Summary

**Line counts / delta:** PRD.md 382 lines, PRD_FINALIZED.md 382 lines — 0% line-count delta; one sentence appended inline within existing line 93 (§2.5).

**Changes (one bullet per change):**
- **§2.5 (The Logical Clock) — insert** — appended one sentence pinning that every date-time value the system emits (clock-stamped fields like `received_at`/`quote_submitted_at`/`released_at`/`issued_at`/`paid_at`/`event_at`, derived instants like `promised_return_at` and `current_utc`, and normalized request-supplied instants like booking `start_time`/`end_time`) is serialized as an ISO 8601 UTC string with exactly three fractional digits (same format §2.2/§2.4 pin for `api_request_timestamp`/`created_at`/`updated_at`), while calendar-date fields (`manufactured_at`, `core_due_date`, `returned_at`) remain `YYYY-MM-DD` — `implementation/db.py:46-52` (`fmt_dt`/`now_iso`: `"%Y-%m-%dT%H:%M:%S." + "%03dZ"`).

**Per-edit pre-edit search log:**
- **(a) Subject:** serialization string format of every date-time value the implementation emits.
- **(b) Impl paths enumerated and read/grepped:** `db.py:46-52` (the single serializer `fmt_dt`, used by `now_iso`); all `now_iso`/`fmt_dt`/`strftime`/`isoformat` call sites greped across every `.py` file: `response.py:15` (`api_request_timestamp`), `helpers.py:26,33,37` (`created_at`/`updated_at`), `helpers.py:204` (traceability `event_at`), `helpers.py:245` (invoice `issued_at`), `routes/invoices.py:48` (`paid_at`), `routes/work_orders.py:42,221,222-224,430,435` (`received_at`, `quote_submitted_at`, `promised_return_at` via `fmt_dt(received_at + contract_tat_hours)`, certificate `issued_at`, `released_at`), `routes/exchange.py:110,164` (`fulfilled_at`, `core_received_at`) and `exchange.py:111` (`core_due_date` = date-only `YYYY-MM-DD`), `routes/test_cells.py:69-70,100-101` (booking `start_time`/`end_time`: request input parsed then re-normalized through `fmt_dt` → `.mmmZ`), `routes/clock_api.py:19` (`current_utc`), `routes/lease.py:71-72,123` (lease `start_date`/`end_date` verbatim date echo; `returned_at` = `current_date().isoformat()` → `YYYY-MM-DD`, a date not a datetime), `routes/units.py:74` (`manufactured_at` verbatim date echo); `routes/customers.py`, `routes/catalog.py`, `routes/requisitions.py`, `app.py`, `errors.py` grep-confirmed to emit no date-time fields beyond base fields; `middleware.py:111-133` is input validation only (accepts any parseable ISO 8601) — not an output path.
- **(c) Wording adjustments from the enumeration:** (1) scoped the claim to values the system *emits* (output serialization), leaving request-input acceptance unpinned per `middleware.py`'s lenient `parse_dt`; (2) explicitly included booking `start_time`/`end_time` and `current_utc` — off-Step-7-site paths that `fmt_dt` also normalizes — so the universal claim holds there; (3) added the calendar-date carve-out (`manufactured_at`, `core_due_date`, `returned_at`) because those fields, despite timestamp-like names, are emitted as `YYYY-MM-DD` date strings (consistent with PRD §3.2/§3.7/§3.8 which already describe them as dates); (4) referenced §2.2/§2.4's existing pin rather than redefining the format, avoiding any double-definition drift.

## Step 9: Complete PRD — 2026-08-13T23:41:52.000Z

All 30 change hunks are in place. The work is complete.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (382 lines / 55,172 chars) → `workspace/PRD_COMPLETED.md` (387 lines / 59,756 chars); char-delta **+4,584**.

**Counts:** 28 ambiguity-pins (inserts where PRD was silent), 2 mismatch-revisions (PRD described different behavior than impl).

### Mismatch revisions (2)

- §4 intro — revise — mismatch — boilerplate said modify/transition → 200; carved out that directive-compliance recording responds `201 Created` although it updates an existing record — `workspace/implementation/routes/work_orders.py:311`
- §2.5 — revise — mismatch — "advances the logical clock" implied forward-only; impl accepts any instant, forward or backward — `workspace/implementation/routes/clock_api.py:15`

### Ambiguity pins (28)

- §2.1 — insert — ambiguity — an `X-User-Role` outside the six recognized roles is rejected with `ERR_FORBIDDEN_ROLE` (403) — `workspace/implementation/middleware.py:36-39`
- §2.2 — insert — ambiguity — `api_request_id` format pinned as `req_` + 20 random alphanumerics — `workspace/implementation/response.py:11-14`
- §2.2 — insert — ambiguity — undefined paths and unsupported methods → `ERR_NOT_FOUND` (404); unhandled failures → `ERR_INTERNAL_ERROR` (500) in the same envelope — `workspace/implementation/app.py:18-28`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, `offset` < 0 → `ERR_INVALID_REQUEST` (400) — `workspace/implementation/middleware.py:139-158`
- §2.3 — revise — ambiguity — list ordering ties on `created_at` broken by server creation order (ubiquitous under the logical clock); traceability ties broken by `created_at` then creation order — `workspace/implementation/helpers.py:45-46`, `workspace/implementation/routes/units.py:118`
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset + limit < total_count`; filters are exact-match equality and never match null fields — `workspace/implementation/response.py:29`, `workspace/implementation/helpers.py:54-58`
- §2.4 — revise — ambiguity — `version` starts at 1 at creation, `updated_at` initially equals `created_at` — `workspace/implementation/helpers.py:25-27`
- §2.5 — insert — ambiguity — `defaulted_exchange_agreement_ids` returned in agreement creation order — `workspace/implementation/helpers.py:306`
- §2.8 — insert — ambiguity — invoices, warranty claims, discrepancy cards, and test-cell bookings (no family 404 code) fall back to generic `ERR_NOT_FOUND` for path identifiers — `workspace/implementation/helpers.py:126-151`
- §2.9 — insert — ambiguity — new paragraph pinning request-body validation (`ERR_INVALID_REQUEST` 400 for missing/malformed/non-object bodies, unknown fields, missing required, type/enum/range violations) and its endpoint-specific position: body-first on quote submission/approval/decline, test-results, and all path-parameter-less creation endpoints; path-existence-first on the other twelve body-carrying endpoints, with booking `work_order_id` and core-return `core_unit_id` resolved after the body — `workspace/implementation/middleware.py:49-136` plus per-handler call order (e.g. `work_orders.py:193-201` vs `requisitions.py:26-27`)
- §2.11 — revise — ambiguity — trace `notes` may also carry a claim id (WARRANTY_INDUCT) — `workspace/implementation/routes/warranty.py:152`
- §2.11 — revise — ambiguity — `DISPOSITION` event type marked reserved; no workflow appends it — no `add_trace(..., "DISPOSITION")` call site exists in `workspace/implementation/`
- §3.2 — insert — ambiguity — ownership/custody combination check fires before serial-number uniqueness — `workspace/implementation/routes/units.py:44-62`
- §3.2 — insert — ambiguity — induction initial work-order field values: `ber_flag` false, estimate/charge/timestamp fields null, counters zero — `workspace/implementation/routes/work_orders.py:34-56`
- §3.3 — insert — ambiguity — discrepancy filing is not gated on work-order status — `workspace/implementation/routes/work_orders.py:139-140` (no state check)
- §3.4 — insert — ambiguity — compliance recording not gated on work-order status; unknown `directive_number` → `ERR_NOT_FOUND` (404); success responds 201 — `workspace/implementation/routes/work_orders.py:298-311`
- §3.4 — insert — ambiguity — requisition filing not gated on work-order status; only `REPAIR_IN_PROGRESS` triggers the auto-move to `AWAITING_PARTS` — `workspace/implementation/routes/requisitions.py:49-51`
- §3.4 — insert — ambiguity — `approved` false from `PMA_REJECTED` → `ERR_REQUISITION_INVALID_STATE` — `workspace/implementation/routes/requisitions.py:82-85`
- §3.5 — insert — ambiguity — no `start_time`/`end_time` ordering constraint enforced beyond the overlap rule — `workspace/implementation/routes/test_cells.py:69-94`
- §3.5 — insert — ambiguity — when several BOOKED windows cover the clock, the earliest-created is consumed — `workspace/implementation/routes/work_orders.py:372-378`
- §3.5 — revise — ambiguity — `cert_number` pinned as sequence zero-padded to six digits starting at `8130-000001` — `workspace/implementation/db.py:37-39`
- §3.6 — insert — ambiguity — every invoice carries the full money-line set with inapplicable lines 0; EXCHANGE/LEASE invoices carry `penalty_variant` `NONE`; `paid_at` null until payment — `workspace/implementation/helpers.py:213-247`
- §3.7 — revise — ambiguity — pool selector adds creation-order final tie-break after `created_at` (never id) — `workspace/implementation/routes/exchange.py:104`
- §3.7 — insert — ambiguity — exchange creation presets: `admin_fee_cents` $250.00, `core_ber_flag` false, pool/core/settlement fields null — `workspace/implementation/routes/exchange.py:43-59`
- §3.7 — insert — ambiguity — core induction hop also clears `owner_customer_id` — `workspace/implementation/routes/exchange.py:141-142`
- §3.7 — insert — ambiguity — default sweep sets pool unit's `owner_customer_id` to the agreement's customer, leaves custody unchanged (`SHIPPED`), and appends no traceability event — `workspace/implementation/helpers.py:293-298`
- §3.9 — revise — ambiguity — DENY requires `denial_reason` present and non-empty — `workspace/implementation/routes/warranty.py:102-105`
- §3.9 — revise — ambiguity — rework work order gets both `labor_estimate_cents` and `labor_charge_cents` set to the original's `labor_charge_cents`, and PENDING DirectiveCompliance records are created for it exactly as at induction — `workspace/implementation/routes/warranty.py:136-153`
- §5 — insert — ambiguity — added `ERR_INTERNAL_ERROR` (500) row matching the §2.2 fallback pin — `workspace/implementation/app.py:26-28`

Everything else in the implementation (all endpoints, role gating, state machines, §2.9 pinned check orderings, BER/TAT/settlement/lease/warranty formulas, rounding rules, exposure invariant, cascades) was already uniquely pinned by PRD_FINALIZED.md and left untouched.

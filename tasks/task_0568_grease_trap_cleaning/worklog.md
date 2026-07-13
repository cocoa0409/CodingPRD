# Worklog — task_0568_grease_trap_cleaning

Scenario: 568. Grease-Trap & Kitchen-Hood Cleaning (FOG compliance): customer/site & equipment profile, scheduled service frequency, pump-out volume & manifest, hood-cleaning certificate & sticker (NFPA 96), FOG-compliance reporting to municipality, route dispatch, emergency call, recurring billing

Difficulty: Expert (passed to prd-bench-scaffold-generator only)

## Step 1: Create Task Directory — 2026-07-09T04:52:47.000Z

Task directory pre-allocated by user: `./tasks/task_0568_grease_trap_cleaning`. Index scan skipped per instruction. Created `workspace/` subdirectory.

## Step 2: Generate Scaffold — 2026-07-09T05:33:32.000Z

All three scaffold artifacts are generated and the lint passes clean. Final verification confirms the structure.

## Summary

Generated a complete **Expert**-tier scaffold for task_0568 (Grease-Trap & Kitchen-Hood Cleaning / FOG compliance), written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0568_grease_trap_cleaning/`:

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single `scaffold_difficulty_design` key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single `scaffold_corner_design` key)

**Scaffold counts**
- Entities: **10** (Customer, Site, Equipment, ServiceContract, Technician, WorkOrder, PumpOutManifest, HoodCertificate, ComplianceReport, Invoice)
- State machines: **6** (Customer, Equipment, ServiceContract, WorkOrder [cyclic recall], ComplianceReport [cyclic reject→revise], Invoice) + 1 concurrency rule (OCC on Customer.version for invoice-create supersede)
- Calculations: **6** (tiered disposal fee, FOG 25% flag, dual-variant invoice, dual-variant site compliance, equipment schedule, outstanding balance)
- Validations: **14** (priority-ordered)
- Endpoints: **40**
- Errors: **22**
- Roles: **5** (Admin, Dispatcher, Technician [entity_backed], ComplianceOfficer, BillingClerk — peer_roles)

**Design instances**
- §1.8 difficulty: **18 instances** — exactly 2 per each of the 9 Difficulty Rules (dual-variant, combinatorial modes a+b, non-linear SMs, depth-3 & depth-2 cascades, two priority-conflict pairs, two boundary metrics, two cross-entity pairs, two overlap semantics, two conserved quantities)
- §1.9 corner: **32 instances** across 8 sections — **25 active** test recipes + **7 `excluded_because` stubs** (each citing a real §1.8 instance)

**Lint:** `scaffold_lint.py` returns `VERDICT: clean lint` — all 298 setup/trigger calls conform to §1.5, and all §1.1 FKs have reverse-reachability GETs.

Two notes: the endpoint count (40) runs above the Expert 20–32 guideline band — a deliberate call given the scenario spans nine distinct capability areas (profiles, frequency, manifest, NFPA-96 cert, municipal reporting, dispatch, emergency, recurring billing); the band is explicitly a soft guideline and every endpoint is load-bearing (creates, folded transition endpoints, and FK reverse-reachability reads). Flat topology uses `api_prefix: "/"` with top-level collections.

## Step 3: Copy Shared Files — 2026-07-09T05:33:32.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0568_grease_trap_cleaning/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-09T05:41:30.000Z

All coverage checks pass. The PRD is complete.

## Summary

**Output:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0568_grease_trap_cleaning/workspace/PRD.md` — 286 lines.

**Section structure:**
- **§1 Introduction** — 2 paragraphs (FOG-compliance business framing + the three-obligation reconciliation angle)
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Service Clock, 2.6 Monetary Precision, 2.7 Optimistic Concurrency, 2.8 Cross-Entity Reconciliation & Cascades, 2.9 Outstanding-Balance Ledger, 2.10 Nested/Filtered Retrieval, 2.11 Validation Order & Error Precedence
- **§3 Business Logic** — 7 lifecycle-grouped subsections: Customer Accounts & Contracts, Sites/Equipment/Schedule, Dispatch & Execution, Pump-Out Manifests, NFPA 96 Certification, Municipal Reporting, Recurring Billing
- **§4 Endpoint Definitions** — 4-column table, 39 endpoints
- **§5 Error Code Catalogue** — 2-column table, 22 error IDs

**Coverage audit (mechanically verified):**

```
Contract 1 — Field-Name Coverage:
- 66 required identifiers (all entities[].fields + request_body/query/path params): 66 present, 0 missing → PASS

Contract 2 — Rule Coverage:
- validations[] with priority: 14 checked, 14 in prose (§2.11 total-order ladder) → PASS
- concurrency_rules[] OCC: 1 checked (POST /invoices + expected_customer_version + ERR_STALE_VERSION/412 + ERR_VERSION_REQUIRED) → PASS
- state_machines[].transitions: 23 checked (Customer 4, Equipment 1, ServiceContract 4, WorkOrder 6, ComplianceReport 5, Invoice 3), all from/to + preconditions+error_id + side-effects → PASS
- calculations[]: 6 checked (disposal fee tiers, FOG flag, invoice provisional/final variants w/ round-per-line, site grade as_of/projected, equipment schedule, balance ledger), reconstructible prose w/ worked examples → PASS
- cascades: WorkOrder-complete L1/L2/L3 and ComplianceReport-accept L1/L2 fully stated → PASS
- errors: all 22 IDs appear in prose trigger AND §5 table → PASS

Contract 3 — §3 Path Purity:
- 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos → PASS

State/enum values: all 36 checked present (PAID/VOID appear inside sanctioned `ISSUED → PAID` / `ISSUED → VOID` transition-pair backticks).
Roles: all 5 named with identity translated (Technician entity-backed ownership; other 4 opaque).
```

Notable disambiguations resolved from the scaffold: period-ordering violations on reports/invoices routed to `ERR_REPORT_PERIOD_INVALID` (422) while work-order window ordering uses `ERR_VALIDATION` (400); pagination violations to `ERR_PAGINATION_INVALID`; the `FAC-` permit prefix to `ERR_DISPOSAL_FACILITY_INVALID` distinct from the type-mismatch check. The withheld difficulty/corner design files were not accessed.

## Step 5: Generate Unit Tests — 2026-07-09T05:59:54.000Z

Everything is complete and verified. Here is the summary.

## Test infrastructure generated for task_0568_grease_trap_cleaning

### Files created

**`test_helpers/`** (Stage 1 — 9 files):
- `types.py` — 13 status enums + `UserRole` + 10 entity TypedDicts (all `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 40 endpoints incl. `_clock`)
- `api_errors.py` — `ApiErrorId` enum + `HTTP_STATUS_CODES` map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions
- `factories.py` — payload factories (input fields only)
- `constants.py` — fee/tier/horizon/threshold constants from the PRD calculations
- `test_users.py` — opaque-role headers + `make_technician_headers(id)` for the entity_backed Technician (identity threading enforced in fixtures)
- `fixtures.py` — low-level creators + composites (`setup_inprogress_grease/hood_work_order`, `setup_issued_invoice`, `setup_suspended_customer_overdue_equipment`, etc.)
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2 — `conftest.py` + 8 test files, **61 tests**).

### Per-queue coverage audit

**Queue A (Difficulty) — 18/18 instances translated, 2 tests each (36 tests). 0 skipped.**
Every instance across all 9 rules (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) passed the PRD-first filter — the PRD carries verbatim, uniquely-derivable prose for each (example-value sentences, §2.11 precedence order, §2.8 cascade chain, §3.4 tier formula, §3.7 tax example). Priority-pair and cross-entity instances got a second complementary test (masking-independent-of-fiscal / safety-independent-of-schedule / positive-control) grounded in the same instance.

**Queue B (Corner) — 25/25 non-stub instances translated, 1 test each (25 tests).**
All non-stub instances across entities, state_machines, calculations, validations, endpoints, errors, cross_cutting_complexity_layers, consistency_model passed the filter.

**Stubs (excluded_because) — 7 total, correctly NOT translated; all `difficulty_instance` cross-references verified to resolve:**
- `calculations/fog_boundary_flag` → `boundary_precision_check/fog_25_percent_inclusive_boundary` ✓
- `errors/dispatch_to_decommissioned_equipment` → `cross_entity_state_dependency/dispatch_requires_equipment_active` ✓
- `errors/issue_for_closed_customer` → `cross_entity_state_dependency/issue_requires_customer_not_closed` ✓
- `errors/no_billable_activity_on_issue` → `boundary_precision_check/zero_billable_lines_boundary` ✓
- `errors/equipment_service_too_soon` → `resource_temporal_overlap/equipment_service_buffer_24h` ✓
- `errors/technician_schedule_conflict` → `resource_temporal_overlap/technician_half_open_overlap` ✓
- `cross_cutting/invoice_void_conserves_balance_stub` → `compensating_invariant/invoice_void_conserves_outstanding_balance` ✓

### Verification performed
- All files byte-compile.
- Every one of the 61 tests carries exactly one `Design:` tag; tag counts confirm 18×2 + 25×1.
- ~40 distinctive citation substrings confirmed verbatim against `workspace/PRD.md` via literal grep.
- No `pytest.mark.skip/skipif/xfail` present; no scaffold/Table/§ leakage in emitted code.
- `workspace/implementation/` was not read or created; no sibling `tasks/` directory was read.

**No gaps/skips within the design indices** — every non-stub instance had verbatim, uniquely-derivable PRD coverage.

## Step 6: Generate Implementation — 2026-07-09T05:59:54.000Z

Fresh boot is empty (no seeding). Implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation of the FOG Compliance Service API in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0568_grease_trap_cleaning/workspace/implementation/`.

### Files created
- `app.py` — full server (single cohesive module: envelope, auth/RBAC, all entities, state machines, calculations, cascades, validation ladder)
- `requirements.txt` — `flask==3.0.3`
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` behind a `flask` import check, `exec python3 app.py`

### Coverage
- **39 endpoints** implemented across Customer, Site, Equipment, ServiceContract, Technician, WorkOrder, PumpOutManifest, HoodCertificate, ComplianceReport, Invoice, plus the `/_clock/set_current_utc` test-driving clock.
- **Storage**: in-memory Python dicts only; store starts empty on every boot (verified) — no seeding, no disk persistence.
- **State machines**: all six (Customer, Equipment, ServiceContract, WorkOrder cyclic recall loop, ComplianceReport cyclic revise loop, Invoice) with preconditions and cascades. WorkOrder-complete cascade (L1 equipment → L2 site compliance → L3 customer suspension lift) and equipment-create suspension cascade implemented; cascaded entities get independent version/updated_at bumps.
- **Calculations** (Decimal, ROUND_HALF_UP): marginal tiered disposal fee (verified 89000 for the PRD example), FOG 25% threshold flag, per-line-then-sum invoice tax (verified 2062/27062 divergence example), provisional vs final invoice variants, equipment service schedule, site compliance grade (7-day as-of vs 30-day projected horizons), outstanding-balance ledger.
- **Validations**: full 14-level precedence ladder from §2.11 (auth → authz/ownership → existence → shape → from-state → referential → safety → service buffer → schedule conflict → equipment availability → completion artifacts → billable activity → fiscal → OCC), with exact error IDs/HTTP codes.
- **Errors**: all 23 catalog codes wired; auth masks body errors, forbidden masks not-found, correct 402/409/412/422 statuses.
- **Details**: response envelope (`meta`/`response_type`/`data`), `req_` request IDs, 3-fractional-digit ISO-8601 timestamps, `X-User-ID`/`X-User-Role` auth with entity-backed Technician ownership, OCC on `expected_customer_version` (ERR_VERSION_REQUIRED / ERR_STALE_VERSION), invoice supersede-prior-DRAFT, logical clock (default `2026-05-01T00:00:00Z`, recompute-on-read), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range checks), `created_at`-ascending sort.

Verified end-to-end with 70 ad-hoc assertions across four smoke scripts (all passing), covering happy paths, every error branch, cascades in both directions, calculation examples, and clean empty reboot.

## Step 7: Run Tests and Iterate — 2026-07-09T06:03:52.000Z

All 8 parallel rounds pass cleanly — 61/61 in every round, 0 failures, 0 errors. (My first summary was a parsing artifact: the JSON uses a `status` field, not `outcome`, so the initial "FAIL" list was spurious. The corrected read confirms a fully green sweep.)

Summary

- Iterations run: 1 (the initial 8-round parallel stability sweep).
- Result: all 8 rounds passed 61/61 tests, 0 failed, 0 errors — no flakiness surfaced across the concurrent sweep.
- Tests deleted: none (no failing tests to triage; nothing was PRD-silent or non-derivable that needed removal).
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

The task at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0568_grease_trap_cleaning` is already in a passing state under the required `per-test-server` isolation. No code or test changes were necessary. Exiting clean.

### Orchestrator independent verification

The subagent self-reported a mid-run parsing confusion, so the orchestrator re-read all 8 `results.*.json` directly rather than trusting the summary:

- results.{1..8}.json — each `passed=61 total=61 failed=0 errors=0` → 8/8 OK
- `pytest.mark.skip|skipif|xfail` occurrences across test_suite/ + test_helpers/: **0**
- `Design:` tags across test_suite/: **61** (one per test, matches Step 5's 18×2 + 25×1 = 61)
- Persistence smells (sqlite / file-write / json.dump / /tmp / pickle) in implementation/app.py: **0**

Clean-sweep claim confirmed.

## Step 8: Finalize PRD — SKIPPED — 2026-07-09T06:03:52.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the test suite exercised, so no `PRD_FINALIZED.md` is produced. Step 9 will therefore start from `PRD.md`.

## Step 9: Complete PRD — 2026-07-09T06:10:17.000Z

Done. All edits are in-paragraph inline revisions; no sections or lines added.

## Summary

- **Source vs completed:** `PRD.md` = 286 lines / 39050 chars; `PRD_COMPLETED.md` = 286 lines / 39772 chars. Char-delta: **+722**. Line count unchanged.
- **Counts:** 4 ambiguity-pins, 2 mismatch-revisions.

### Changes
- **§2.8 Cross-Entity Reconciliation** — revise — mismatch — the blanket "each secondary mutation increments version" implies the site always bumps on re-grade; pinned that a site's `updated_at`/`version` advance only when the re-grade actually changes `compliance_status`/`projected_compliance_status`, matching the conditional `if before != after: touch(site)` guard — `app.py:780-781, 820-822, 1124-1126, 1178-1180, 1216-1218`.
- **§3.2 Sites/Equipment** — revise — mismatch — "All comparisons are day-granular" contradicts impl, which compares exact instants (`nd < now`, `nd < now + timedelta(days=7/30)`, `last + timedelta(days=freq)`); revised to state exact-instant comparison, not day-truncated — `app.py:349-356, 370-388`.
- **§3.4 Pump-Out Manifests** — insert — ambiguity — PRD only said "mints a `manifest_number`"; pinned the `MFT-` prefix — `app.py:1166`.
- **§3.5 Hood Certification** — insert — ambiguity — PRD only said "mints a `sticker_number`"; pinned the `NFPA96-` prefix — `app.py:1247`.
- **§3.7 Recurring Billing (line selection)** — insert — ambiguity — PRD said "one line per included work order" without stating scope; pinned that work orders are selected by owning customer (via site) + period/status rules, independent of the invoice's `contract_id` — `app.py:601-619` (`invoice_lines` filters on `workorder_customer_id`, never on `contract_id`).
- **§3.7 Recurring Billing (provisional window)** — insert — ambiguity — PRD said provisional "counts work orders in the period" without naming the timestamp; pinned that provisional selection uses `planned_start` in the half-open `[period_start, period_end)` window (whereas final uses `completed_at`) — `app.py:608-611`.

Two items I deliberately did not change (impl imposes no constraint and PRD imposes none, so no silence/mismatch to pin): work-order creation does not require `equipment_id` to belong to the named `site_id`, and manifest/certificate filing imposes no work-order from-state check. Response envelope, error precedence, monetary/tax rounding, disposal-fee tiers, state machines, defaults, and all other field shapes already match the implementation uniquely.

### Orchestrator verification

- `workspace/PRD_COMPLETED.md` exists (39772 bytes); `workspace/PRD_FINALIZED.md` correctly absent (Step 8 skipped).
- `diff PRD.md PRD_COMPLETED.md` → 6 changed lines (111, 164, 182, 190, 206, 208), 12 diff lines total, 0 additions/deletions of lines. Minimal-patch contract satisfied.
- `workspace/implementation/` contains exactly `app.py`, `requirements.txt`, `start.sh`, `results.{1..8}.json` — no stray smoke scripts, no `__pycache__`, no persisted state.

## Pipeline Complete — 2026-07-09T06:10:17.000Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final state: 61/61 tests passing across 8/8 parallel stability rounds under `--isolation per-test-server`.

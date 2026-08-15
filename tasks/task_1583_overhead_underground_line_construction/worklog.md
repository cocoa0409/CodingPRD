# Worklog — task_1583_overhead_underground_line_construction

## Step 1: Create task directory — 2026-08-13T23:23:00.000Z

Pre-created and pre-assigned by the pipeline invoker: `tasks/task_1583_overhead_underground_line_construction/workspace/`. Step 1 treated as DONE per invocation instructions; no index scan performed.

## Step 2: Generate scaffold — 2026-08-14T00:01:53.787Z

All three artifacts generated and lint-clean. Summary:

### Files written

- `tasks/task_1583_overhead_underground_line_construction/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `tasks/task_1583_overhead_underground_line_construction/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `tasks/task_1583_overhead_underground_line_construction/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

### Scaffold contents

**Complexity profile**: ledger_reconciliation + temporal_windowing; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; hierarchical topology, cyclic state machines, approval-chain roles, immediate consistency.

**Entities (14)**: Contract, BidItem (unit-price schedule), WorkPackage, Crew, Equipment, Assignment, ProductionEntry, StockItem, MaterialIssue, Inspection, OutageRequest, StormActivation, SafetyEvent, Invoice. Computed cross-entity fields include `BidItem.accepted_quantity`/`billed_quantity`, `WorkPackage.rework_open_count`/`open_material_issue_count`, `StockItem.on_hand`, `Crew.status`/`Equipment.status` (derived from assignments + storm activations against the logical clock).

**State machines (10)**: non-linear ones include ProductionEntry rework cycle (SUBMITTED→REWORK_REQUIRED→SUBMITTED→ACCEPTED), Invoice revision cycle (SUBMITTED→REJECTED→DRAFT), Contract ACTIVE↔SUSPENDED, OutageRequest APPROVED→CHANGE_REQUESTED→APPROVED. OutageRequest has a clock-driven auto-transition APPROVED→IN_EFFECT.

**Concurrency (2 OCC rules)**: `production-entry-create-stale-assignment` (expected_assignment_version) and `invoice-create-stale-work-package` (expected_work_package_version), both ERR_STALE_VERSION/412.

**Calculations (8)**: billing_extension (tiered overrun at 110% threshold, provisional/final variants), invoice_total_aggregation (pinned per-line-round-then-sum), storm_premium_pay (standby_convert vs pure_callout with 4h minimum), quantity_cap_check (125% inclusive cap), material_reconciliation and billing_pool_reconciliation (the two conservation invariants), production_acceptance_accounting, crew_equipment_status_derivation.

**Validations (30)** ordered auth → forbidden → body-shape → existence → OCC → contract state → entity state → safety (outage coverage, equipment down) → constraints (overlaps, buffers, caps) → referential (cross-contract) → fiscal (period overlap, billable units, stock).

**Endpoints (61)**, including `GET /work-packages/{id}/billing-preview` (computed read with variant) and `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z). **Errors (29)**, all triggered by at least one design instance. **Roles (5, all opaque)**: CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER.

**Difficulty design**: 18 instances, 2 per rule, each with structured `setup_api_calls`/`trigger`/`assert` and hand-computed literals (e.g., provisional 5500.00 vs final 3000.00 subtotal; premium 540.00 vs 480.00; overrun line 110×50 + 10×40 = 5900.00; per-line rounding 200.02 vs 200.01; cascades: inspection-FAIL → entry → rework count → DRAFT invoice hold_reason (depth 3) and FATAL incident → contract SUSPENDED → assignments/outages CANCELLED (depth 2)).

**Corner design**: 54 instances across all nine guide sections — 40 with full test recipes (defaults, required fields, enums, 404, pagination envelope, computed crew status, invalid/terminal transitions, date-window activation, input-set filtering, all remaining error triggers, RBAC denials, both OCC stale-version paths, FK reverse-reachability lists, immediate consistency) + 14 `excluded_because` stubs citing difficulty instances.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(61 endpoints, 14 entities, 18 §1.8 + 40 §1.9 instances, 621 calls scanned.) Forbidden-vocabulary scan is clean, instance names are unique across both files, and all stub references resolve.

## Step 3: Copy shared files — 2026-08-14T00:02:19.530Z

Copied `./INSTRUCTION.md` → `tasks/task_1583_overhead_underground_line_construction/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T00:20:30.000Z

All audits pass. The PRD is complete at `tasks/task_1583_overhead_underground_line_construction/workspace/PRD.md`.

### Summary

**Output:** `tasks/task_1583_overhead_underground_line_construction/workspace/PRD.md` — 339 lines.

**Section list:**
- §1 Introduction (2 paragraphs — utility unit-price contracting context + approval-chain operating model)
- §2 Global Specifications (10 subsections): 2.1 RBAC (all 5 roles named, opaque identity translated per role), 2.2 API Response Structure (byte-for-byte verbatim match with the canonical source file), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending), 2.4 Resource Identity/Versioning (incl. parent-version bump rules), 2.5 Logical Clock (startup default 2026-08-01T00:00:00Z, lazy `IN_EFFECT`), 2.6 OCC (both rules, stale-version framing only), 2.7 Rounding Discipline, 2.8 Conservation Principles (stock + billable pool), 2.9 Validation Order (11-step precedence ladder + left-to-right path resolution), 2.10 Stop-Work Authority (suspension cascade + exemptions)
- §3 Business Logic (9 subsections organized by lifecycle/domain process): contract setup, crews/equipment/assignments, daily production + quantity ceiling, material stewardship, inspection/rework loop, outage coordination, storm duty + premium pay, safety/resumption, progress billing
- §4 Endpoint Definitions (61 rows, 4 columns only)
- §5 Error Code Catalogue (29 rows, 2 columns only)

**Hard Contract Reports:**

- **Contract 1 (Field-Name Coverage):** 91 required identifiers (entity fields + line fields + endpoint inputs + query params + path params), 91 present, 0 missing. **PASS**
- **Contract 2 (Rule Coverage):** validations priority ordering expressed (§2.9 ladder, 11 rungs); 2/2 OCC rules expressed with write-endpoint + `expected_assignment_version`/`expected_work_package_version` + `ERR_STALE_VERSION`/412; all 42 state-machine transitions fully expressed with preconditions, error IDs, and side-effect cascades; all 8 calculations in precise reconstructible prose (incl. pinned rounding order with the 100.005→200.02 worked example, both storm-pay variants, floor phrasing for the overrun threshold); all 29 validations matchable to their error IDs with full `applies_to` enumeration (e.g., `ERR_OPEN_REWORK` on both work-package completion and invoice submission; `ERR_INVALID_DATE_RANGE` on all four endpoints); sibling branches symmetric (outage approve/deny from both source states, reconcile two-path, invoice void from three states). **PASS**
- **Contract 3 (§3 Path Purity):** 471 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**

**Coverage-audit notes:**
- The mechanical audit initially reported false Contract-1 misses because the token extractor mis-paired backticks across §2.2's ```json fences; stripping fenced blocks first resolved it — the PRD itself was correct (verified: no lines with odd backtick counts outside fences).
- All 54 enum/state values appear backticked and exact; all 29 error IDs appear in §1–§3 prose (not just the §5 table).
- No fuzzy/approximating words, no pseudocode operators (`==`, `<=`, `->`, `:=`, etc.) anywhere in prose; OCC section contains no race/timing-overlap framing.
- Boundary inclusivity preserved verbatim from scaffold: quantity-cap equality allowed (125%), stock draw to exactly zero allowed, 60-minute outage buffer with exactly-one-hour passing, `window_end` strictly after `window_start`, assignment/invoice period ends on-or-after starts.
- The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate unit tests — 2026-08-14T00:38:00.000Z

Test generation for task_1583 is complete. Summary:

### Test counts

**Queue A (Difficulty) — 36 tests, 18/18 instances at exactly 2 tests each:**
- dual_variant_calc: billing_preview_provisional_vs_final, standby_convert_vs_pure_callout_premium
- combinatorial_formula: overrun_tier_split_pricing, per_line_rounding_then_sum
- non_linear_state_machine: production_entry_rework_cycle, invoice_rejection_revision_cycle
- transitive_cascade: inspection_fail_cascade_to_invoice_hold, fatal_incident_cascade_suspends_contract
- priority_pair_validation_conflict: state_error_beats_fiscal_on_invoice_resubmit, outage_safety_beats_quantity_cap
- boundary_precision_check: material_issue_exact_on_hand_boundary, quantity_cap_equality_boundary
- cross_entity_state_dependency: production_requires_in_effect_outage, completion_requires_material_reconciliation
- resource_temporal_overlap: crew_assignment_closed_interval_overlap, outage_window_sixty_minute_buffer
- compensating_invariant: stock_issue_return_conservation, invoice_submit_void_pool_conservation

**Queue B (Corner) — 39 tests covering 39/40 non-stub instances** (1 skipped, see below). All 14 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.

**Total: 75 tests, all collected cleanly by pytest.**

### Files written

`test_helpers/` (9 files): `types.py` (14 TypedDicts, 16 enums), `api_client.py` (65 endpoint methods covering all PRD §4 rows), `api_errors.py` (29 errors + framework status-map registration), `assertions.py` (14 entity assertions), `factories.py`, `constants.py` (0.10/1.10/1.25 defaults, 0.5x/2.0x/4h storm constants, 60-min buffer, clock default), `test_users.py` (5 opaque roles), `fixtures.py` (composite chains: `setup_active_contract`, `setup_mobilized_scenario`, `setup_field_scenario`, OCC-aware `report_production`/`create_draft_invoice`, `inspect_entry`/`accept_entry`/`fail_entry`, stock/storm/outage helpers, `suspend_contract_via_incident`), `__init__.py` barrel.

`test_suite/` (12 files): `conftest.py` + 11 concern-grouped test files (`test_01` contract setup/auth … `test_11` envelope/reverse-reachability).

### Instances skipped (1)

- `Corner/errors/all_remaining_errors_triggerable` — not an API-observable claim: empty `setup_api_calls` and `trigger`, and its sole assert ("mapping exists for all 29 error ids") is a design-time cross-reference audit, not a behavior any PRD sentence pins on the API. Its substance is satisfied: all 29 error ids are asserted by at least one generated test (verified programmatically, 29/29).

### Deliberate assertion narrowing (PRD unique-derivability)

- `contract_creation_applies_defaults`: the instance's `version == 1` sub-assertion was omitted — PRD §2.4 says version "increments by one on every modification" but never pins the initial value (a PRD-only reader could start at 0 or 1). The PRD-covered claims (defaults 0.10/1.10/1.25, status DRAFT) are asserted.
- `occ_stale_assignment_version_rejected`: the literal "version advanced to 3" was replaced by the PRD-derivable relation `v_after == v_before + 1` (PRD §2.4: "posting a production entry increments the parent assignment's `version` by one"), same for the work-package OCC test.

### Stage-audit verdicts

- **Syntax/import**: all files compile; `test_helpers` imports cleanly; 75 tests collect under `PYTHONPATH=.` with the pip-installed framework.
- **Coverage audit**: PASS — 18/18 difficulty instances ≥2 tests; 39/40 corner non-stub ≥1 (1 deliberate skip above); 14/14 stub cross-references resolve.
- **PRD-citation pass**: PASS — 117 citations extracted from docstrings, every one verbatim-matches PRD.md after whitespace normalization; all citations are rule-bearing (error ids, thresholds, transitions, side effects), not endpoint-titular; all asserted error ids appear in PRD prose.
- **Scaffold-citation pass**: PASS — every test docstring ends with exactly one `Design:` line resolving to a real instance; no untagged/dual-tagged tests.
- **Hygiene**: no `skip`/`skipif`/`xfail`; no "scaffold"/"Table N"/"§1.x" vocabulary in generated code; no unused imports.

## Step 6: Generate implementation — 2026-08-14T00:38:00.000Z

Implementation complete. Summary:

### Files written (all under `tasks/task_1583_overhead_underground_line_construction/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` (no-op on per-test reboots), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/fallback handlers
- `db.py` — in-memory store (14 collections, **empty at boot, zero seeding**)
- `errors.py` — all 29 catalog error IDs with exact HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list responses add `limit/offset/total_count/has_more` in meta
- `middleware.py` — auth on `X-User-Role` only (X-User-ID opaque per PRD §2.1), 401/403
- `util.py` — UUIDs, 3-fractional-digit timestamps, logical clock (default `2026-08-01T00:00:00Z`, regression rejected), Decimal helpers with `ROUND_HALF_UP`
- `validate.py` — shape validation (priority 3) and path/body existence (priority 4)
- `routes/` — contracts, bid_items, work_packages, resources (crews+equipment), assignments (+production entries), stock (+material issues), inspections, outages, storm, safety, invoices (+billing-preview), clock, helpers
- `services/core.py` — record lifecycle + all derived fields; `services/billing.py` — tiered billing and storm premium pay

### Endpoint count

**61** (verified via url_map enumeration; matches the PRD §4 table exactly).

### Noteworthy design decisions

1. **Derived fields computed on read, never stored**: `BidItem.accepted_quantity`/`billed_quantity`, `StockItem.on_hand`, `WorkPackage.rework_open_count`/`open_material_issue_count`, `Invoice.hold_reason`, DRAFT invoice lines/totals, and Crew/Equipment status are all recomputed from the ledger at serialization. This makes both conservation principles (stock units, billable pool) exact by construction and makes the FAIL-inspection/rework/void cascades automatic — no counter drift possible. Stored mutations still bump `version` per PRD §2.4 (transitions incl. cascaded ones, receipt → stock item, entry create → assignment, assignment/invoice create → work package).
2. **Validation ladder** follows PRD §2.9 strictly: auth → role → shape → existence (path left-to-right, then body FKs) → OCC (412, before any state evaluation) → contract activity (SUSPENDED vs NOT_ACTIVE) → lifecycle → work-safety (outage/equipment-down) → business constraints → cross-contract (409) → fiscal. Per-transition actor roles on contract/invoice transitions return 403 after the (from,to) pair is validated.
3. **Billing formula implemented literally per scaffold/PRD**: `eligible` = bid-item entries with `work_date` in period (status by variant); `already_billed` = this work package's frozen SUBMITTED/APPROVED/PAID lines; `prior_cumulative_accepted` = accepted minus in-period accepted positions the floored `est × overrun_threshold_pct` boundary; per-component HALF_UP rounding pinned before summation. REJECTED invoices release the billed pool immediately (the {SUBMITTED,APPROVED,PAID} set appears in the entity field, §2.8, and the billing formula).
4. **Lazy IN_EFFECT**: outage sweep runs on clock-set, outage reads/lists, and whenever an outage is referenced (decide/release/production outage-gate); date-granularity coverage check for `requires_outage` production.
5. **Storm premium dispatch on the `converted` flag** (PRD: "the converted flag decides"): pure call-out gets the 4-hour minimum at 2×, standby-convert gets 0.5× standby + 2× worked with no minimum, components rounded separately.
6. **Safety exemption honored**: safety-event review transitions and all GETs bypass the SUSPENDED gate so resume stays reachable; suspension cascade cancels PLANNED/ACTIVE assignments and REQUESTED/APPROVED/CHANGE_REQUESTED outages contract-wide, each version-bumped.

Verified with ~120 end-to-end smoke assertions across five fresh server boots (auth/envelope, contract & schedule lock, assignment windows/conflicts, OCC 412s, quantity cap boundary, rework loop + invoice holds, outage buffer/lazy effect, material ledger conservation, storm premium variants, suspension cascade/resume, tier-split billing math, rounding pin, pool conservation on submit/void/revise, pagination meta) — all passing, plus a clean `bash start.sh` boot check.

## Step 7: Run tests and iterate — 2026-08-14T00:45:00.000Z

All 8 parallel rounds pass 75/75 with zero errors, zero failures, zero skips — a clean sweep on the first iteration. No fixes or deletions were needed.

### Summary

- **Iterations run**: 1 (clean 8-round parallel sweep, 75/75 passed in every round)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `implementation/`**: none

The existing implementation at `tasks/task_1583_overhead_underground_line_construction/workspace/implementation/` (built per the worklog's Step 6) already satisfies the full test suite deterministically across all 8 concurrent per-test-server isolation rounds. No flakiness surfaced — every test passed in every round, so there was no union of failures to diagnose.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T00:45:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T01:05:00.000Z

All edits applied. PRD_COMPLETED.md is complete — 18 edit operations covering 31 distinct pins/revisions. Summary:

### Summary

**Source:** `workspace/PRD.md` (no PRD_FINALIZED.md existed — Step 8 skipped). Copied to `workspace/PRD_COMPLETED.md`, edited in place only.

**Size:** PRD.md 339 lines / 56,464 chars → PRD_COMPLETED.md 341 lines / 60,761 chars (**char-delta +4,297**; +2 lines from one intra-section paragraph split in §2.9; no new sections added).

**Counts:** 26 ambiguity-pins, 5 mismatch-revisions.

#### Ambiguity pins (PRD silent → inserted impl behavior)

- §2.1 — insert — ambiguity — missing `X-User-ID` is never rejected; only the role header gates access — implementation/middleware.py:19-25
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — implementation/routes/helpers.py:14-44
- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending — implementation/routes/helpers.py:101
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/services/core.py:19
- §2.5 — insert — ambiguity — clock regression rejected with `ERR_INVALID_REQUEST`; re-setting the same instant accepted — implementation/util.py:61-68
- §2.9 — insert — ambiguity — body foreign-key refs resolve in §3 naming order (`crew_id` before `equipment_id`) — implementation/routes/assignments.py:48-49
- §2.9 — insert — ambiguity — uniqueness constraints (`contract_number`, `item_code`/`material_code` per contract, `crew_code`, `equipment_code`) enforced as `ERR_INVALID_REQUEST` after shape/existence, before lifecycle gates — implementation/routes/contracts.py:41-44,129-133; resources.py:26-29,61-64; stock.py:39-42
- §2.9 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — implementation/app.py:31-37
- §2.10 — insert — ambiguity — gate explicitly covers work-package creation and production resubmission/voiding — implementation/routes/work_packages.py:42; assignments.py:251,274
- §2.10 — insert — ambiguity — stock-item registration and receipts sit outside the gate, available under any contract status — implementation/routes/stock.py:30-62
- §3.1 — insert — ambiguity — `effective_end` before `effective_start` → `ERR_INVALID_REQUEST` — implementation/routes/contracts.py:38-39
- §3.1 — insert — ambiguity — `overrun_threshold_pct`/`quantity_cap_pct` stored as supplied, no range validation — implementation/routes/contracts.py:33-35
- §3.1 — insert — ambiguity — contract transition: bad `to` → `ERR_INVALID_REQUEST`; undefined source→target pair → `ERR_INVALID_STATE` checked *before* the per-transition role check → `ERR_FORBIDDEN` — implementation/routes/contracts.py:72-87
- §3.2 — insert — ambiguity — assignment transition `to` outside {ACTIVE, COMPLETED, CANCELLED} → `ERR_INVALID_REQUEST` — implementation/routes/assignments.py:150-152
- §3.3 — insert — ambiguity — quantity ceiling uses the bid item's own contract's `quantity_cap_pct` (checked before cross-contract rule) — implementation/routes/assignments.py:210-213
- §3.3 — insert — ambiguity — resubmission re-applies only the quantity ceiling, not the other creation-time gates — implementation/routes/assignments.py:243-263
- §3.4 — insert — ambiguity — returns accepted only while the issue stands `OPEN`, else `ERR_INVALID_STATE` — implementation/routes/stock.py:136-138
- §3.4 — insert — ambiguity — `quantity_installed` must be zero or greater — implementation/routes/stock.py:151
- §3.6 — insert — ambiguity — denial from `CHANGE_REQUESTED` leaves `requested_window_*` populated; only re-approval clears them — implementation/routes/outages.py:103-104
- §3.7 — insert — ambiguity — convert/close/cancel each require `ACTIVE` status, else `ERR_INVALID_STATE` — implementation/routes/storm.py:53-60
- §3.8 — insert — ambiguity — safety transition `to` outside {UNDER_REVIEW, CLOSED} → `ERR_INVALID_REQUEST` — implementation/routes/safety.py:78
- §3.9 — insert — ambiguity — invoice lines emitted in bid-item creation order — implementation/services/billing.py:59-61
- §3.9 — insert — ambiguity — provisional preview's prior-cumulative subtraction still uses final-basis (`ACCEPTED`-only) eligible units — implementation/services/billing.py:71-73
- §3.9 — insert — ambiguity — invoice transition: bad `to` → `ERR_INVALID_REQUEST`; per-transition role check (`ERR_FORBIDDEN`) precedes source-state check (`ERR_INVALID_STATE`) — implementation/routes/invoices.py:111-124
- §3.9 — insert — ambiguity — voiding a `DRAFT` invoice freezes the then-current live computation as the snapshot later reads return — implementation/routes/invoices.py:149-157
- §3.9 — insert — ambiguity — billing-preview: query-param validation errors (`ERR_INVALID_REQUEST` / `ERR_INVALID_DATE_RANGE`) and response shape (`status` DRAFT, null `hold_reason`) — implementation/routes/invoices.py:164-199

#### Mismatch revisions (PRD prose ≠ impl → revised to impl)

- §2.6 — revise — mismatch — production OCC: "version has advanced since that read" → "supplied value does not equal the assignment's current version" (impl rejects any `!=`) — implementation/routes/assignments.py:187
- §2.6 — revise — mismatch — invoice OCC: same "does not equal" revision — implementation/routes/invoices.py:39
- §2.4 — revise — mismatch — dropped "derived-field recomputation" as version-bumping; pinned that computed fields re-derive on read and never bump the hosting resource's `version` — implementation/services/core.py (derived getters never call `touch`)
- §2.8 — revise — mismatch — `billed_quantity`/remaining-billable pool is summed over the **contract's** frozen non-VOID invoice lines, not "the same work package's" — implementation/services/core.py:95-106
- §3.4 — revise — mismatch — exact-match reconciliation open to "either a foreman or the project manager" (prose said foreman only) — implementation/routes/stock.py:149,165-175

Notable impl quirk now pinned: contract transitions check state-pair validity *before* the per-transition role, while invoice transitions check role *before* source state — both orders are now explicitly pinned in their respective sections.

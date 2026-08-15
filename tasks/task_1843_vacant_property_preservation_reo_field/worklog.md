# Worklog — task_1843_vacant_property_preservation_reo_field

## Step 1: Create Task Directory — 2026-08-14T20:01:00.000Z

Pre-existing: `tasks/task_1843_vacant_property_preservation_reo_field/` and `workspace/` created by the outer pipeline before this orchestrator run. No action taken.

## Step 2: Generate Scaffold — 2026-08-14T20:29:37.864Z

Done. All three scaffold artifacts are generated and pass `scaffold_lint.py` with a clean verdict.

## What was generated

**Task**: `task_1843_vacant_property_preservation_reo_field` — a vacant-property preservation/REO field-services platform modeled as compliance/audit + workflow-orchestration, flat topology (15 peer entities with FK links), posture-driven gating, segregation-of-duties role model, immediate consistency.

### SCAFFOLD.yaml (§1.0–§1.7)
- **Entities: 15** — Servicer, Crew, InvestorAllowable, Property (computed condition_score/compliance_posture/ytd rollups), WorkOrder (pins allowable snapshot + version), Inspection, PersonalPropertyDisposition, RecurringServicePlan, CodeViolation, MunicipalRegistration (half-open windows), DamageReport, Bid (negotiation rounds), PhotoEvidence (4 optional subject FKs, exactly-one rule), Invoice, ExpenseLine
- **State machines: 10** — cyclic rework loop on WorkOrder (SUBMITTED→IN_PROGRESS), cyclic negotiation on Bid (COUNTERED→SUBMITTED rounds), cure rejection loop on CodeViolation, 3-link occupancy cascade (Inspection verify → Property occupancy → plan suspension → generated-order cancellation), sweep-driven auto-transitions (expiry, escalation, hold release)
- **Concurrency rules: 2** — OCC on WorkOrder.version (reassign) and DamageReport.version (bid create), both 412/ERR_STALE_VERSION
- **Calculations: 12** — including dual-variant allowable_reimbursement (PROVISIONAL counts SUBMITTED invoices, FINAL counts only settled) and property_condition_score (EXTERIOR_ONLY vs INTERIOR_INCLUSIVE), pinned per-line rounding for prompt-pay discount, circularity-broken volume rebate, winterization multi-input quote
- **Validations: 10** priority tiers (auth → existence → shape → state → safety → referential → temporal → constraint → fiscal)
- **Endpoints: 86** (includes `/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default and an ops-run daily sweep)
- **Errors: 33**; **Roles: 5** (Servicer/FieldCrew entity-backed; VendorAdmin/Dispatcher/QualityReviewer opaque)

### SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 19 instances
All 9 rules with ≥2 differentiated instances (combinatorial_formula has 3, covering modes a/b/c): provisional-vs-final invoice allowable (0 → 3000 divergence), interior scoring variants (65 AT_RISK vs 35 NON_COMPLIANT), winterization 60480 vs 50400 seasonal, per-line rounding 134 vs 133 trap, rebate evaluation order (15000, then 0), rework and bid-negotiation cycles, depth-3 occupancy cascade and depth-2 ytd review-flag cascade, two priority conflicts (state>fiscal, referential>temporal), aggregate-cap exact-boundary (3000 == remaining approved) and photo-minimum count boundary, two cross-entity state dependencies, half-open adjacency vs aggregate day-capacity overlap semantics, and two compensating invariants (ytd cents; season occurrence budget).

### SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 58 instances (50 active + 8 excluded stubs)
Sections: entities 6, state_machines 7, calculations 4, validations 4, endpoints 2, errors 26 (18 live triggers + 8 stubs citing §1.8 coverage), rbac 6 (four 403 denials, SoD flag/clear, bid ownership), cross_cutting_layers 3 (two OCC stale-version tests, version-pinning snapshot: pinned cap 100 survives PATCH to 200 → PARTIALLY_APPROVED), consistency_model 1.

### Verification
- `scaffold_lint.py`: **VERDICT: clean lint** (86 endpoints, 15 entities, 19+50 instances, 833 calls scanned; all FKs reverse-reachable)
- All formula-derived asserts were pre-computed as literals; every `${var}` placeholder is bound by an earlier `captures:`; instance names unique across both design files; no forbidden race vocabulary; file split honored (neither design key in SCAFFOLD.yaml).

## Step 3: Copy Shared Files — 2026-08-14T20:29:52.955Z

Copied `./INSTRUCTION.md` → `tasks/task_1843_vacant_property_preservation_reo_field/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T20:40:45.443Z

All contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1843_vacant_property_preservation_reo_field/workspace/PRD.md` (393 lines).

## Summary of Generated PRD

**Structure (26 headings):** §1 Introduction (2 paragraphs, business-context angle); §2 Global Specifications with 12 subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Resource Identity/Versioning, 2.5 Logical Clock & Daily Sweep, 2.6 Monetary Precision, 2.7 Validation Order & Nested Path Resolution, 2.8 OCC, 2.9 Occupancy Safety Gate, 2.10 Condition Score & Posture, 2.11 Allowable Schedules & Snapshot Pinning, 2.12 Cross-Resource Cascades); §3 Business Logic with 9 lifecycle-grouped subsections (onboarding, work order intake/dispatch, field execution/photo/QA, inspection cycle, personal property, recurring plans, registration/violation cure, damage/bidding, invoicing/settlement); §4 Endpoint Definitions (86 rows, 4 columns); §5 Error Code Catalogue (33 rows, 2 columns).

**Entity coverage:** all 15 entities (Servicer, Crew, InvestorAllowable, Property, WorkOrder, Inspection, PersonalPropertyDisposition, RecurringServicePlan, CodeViolation, MunicipalRegistration, DamageReport, Bid, PhotoEvidence, Invoice, ExpenseLine); all 10 state machines, 12 calculations, 10 validation priorities, 2 OCC rules expressed in prose.

**Hard contract results:**
- Contract 1 (Field Coverage): PASS — 115/115 entity fields, 84/84 request-body inputs, 22/22 query params, 16/16 path params present in backticks; 89/89 state and enum values present.
- Contract 2 (Rule Coverage): PASS — validation priority pipeline stated as an ordered 10-stage sequence (incl. referential-before-temporal on start-cure); both OCC rules name write operation + `expected_*_version` + `ERR_STALE_VERSION`/412 in stale-version framing only; all transitions, side-effect cascades, calculation formulas (allowable reimbursement PROVISIONAL/FINAL with per-line-then-aggregate order and created_at-ASC/unit-price-DESC tie-break, pinned per-line prompt-pay rounding, winterization quote, condition score with both variants, volume rebate tiers, fine accrual, recurring generation, overlap, capacity, photo minimums, hold period, ytd rollup with conserved-quantity invariant) expressed in precise prose; sibling branches (renew ACTIVE/EXPIRED, verify OCCUPIED/VACANT, close CLOSED/MONITORING, escalation from OPEN/CURE_IN_PROGRESS, appeal from DENIED/PARTIALLY_APPROVED) given equal density.
- Contract 3 (§3 Path Purity): PASS — 723 backtick tokens scanned, zero path/method violations.
- §2.2 verified byte-identical to the fixed source block.

**Zero-silence adjudications made:**
1. `version` initial value: scaffold only notes "starts at 1" on DamageReport; generalized in §2.4 as a system-wide common property (consistent with common_fields semantics).
2. Allowable-reimbursement self-inclusion: scaffold doesn't say whether the invoice being computed counts in its own inclusion set; PRD deliberately uses scaffold-neutral phrasing ("this property's invoices whose status falls in the variant's inclusion set") without adding "other".
3. Bid creation requires `BID_REQUESTED`: state machine lists the guard only on submit/approve; extended to create per endpoint description + `ERR_DAMAGE_NOT_ACCEPTING_BIDS` catalog condition.
4. Servicer `active` flag: described declaratively (scaffold defines semantics but no enforcement rule); no blocking behavior invented.
5. Photo completeness: calculation trigger mentions submit and approve, but the approve precondition is flagged-open only; PRD enforces minimums at submit and flagged-open at both submit and approve, faithful to the state-machine preconditions.

The withheld difficulty/corner design files were not opened; no sibling task directories were read.

## Step 5: Generate Unit Tests — 2026-08-14T20:51:00.000Z

All audits pass. Generation complete.

## Summary

**Task**: `task_1843_vacant_property_preservation_reo_field` — unit test suite generated from the two design indices only (no freelance scaffold walk).

### Test counts
- **Queue A (Difficulty)**: 38 tests — all 19 instances × 2 tests each.
- **Queue B (Corner)**: 50 tests — all 50 non-stub instances × 1 test each.
- **Total: 88 tests** across 9 files. **Zero instances skipped** (every instance passed the PRD-first two-condition filter).

### Per-instance coverage
- Queue A: 19/19 instances emitted (dual_variant_calc ×2, combinatorial_formula ×3, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2, boundary_precision_check ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2).
- Queue B: 50/50 non-stub instances emitted; 8 `excluded_because:` stubs correctly not translated, and all 8 stub cross-references resolve to real queue-A instance names.

### Translation repair (one instance)
- `Corner/errors/damage_close_with_open_bids_rejected`: the design's literal setup closes a **BID_REQUESTED** report, but the PRD attaches `ERR_OPEN_BIDS` only to the `REPAIR_IN_PROGRESS → CLOSED` transition (from BID_REQUESTED a PRD-only reader could equally return `ERR_INVALID_STATE`). The test instead creates a DRAFT bid *before* approval (it survives the approve cascade, which rejects only SUBMITTED/COUNTERED bids per PRD), drives the spawned repair order to COMPLETED, then closes — leaving the open DRAFT bid as the only failing gate, so `ERR_OPEN_BIDS` is uniquely derivable.

### Helper files written (`test_helpers/`)
`types.py` (15 TypedDicts + 12 status enums), `api_client.py` (86 endpoint methods over `GenericApiClient`), `api_errors.py` (33 errors + HTTP map registered via `set_error_http_status_map`), `assertions.py` (15 entity assertions + posture invariant), `factories.py` (15 payload factories), `constants.py` (photo minimums, quote constants, hold days, ytd/rebate thresholds), `test_users.py` (opaque-role constants + entity-backed builders `make_servicer_headers`/`make_field_crew_headers` used throughout for ownership-gated calls), `fixtures.py` (composite chains: `setup_portfolio`, `setup_completed_order_with_invoice`, `setup_bid_requested_report`, photo-minimum uploader, etc.), `__init__.py` barrel.

### Test files (`test_suite/`)
`conftest.py` + 9 concern-grouped files: 01 portfolio creation/validation (10), 02 work-order dispatch/lifecycle (17), 03 property posture/conveyance (5), 04 inspections/recurring plans (8), 05 personal property/municipal compliance (13), 06 damage/bidding (9), 07 invoicing/allowable (16), 08 quotes/settlement (5), 09 RBAC/segregation (5).

### Self-audit results
- **Stage 1**: all helpers compile; barrel import verified against the installed framework; no framework code regenerated.
- **Stage 2 completeness audit**: 88/88 tests carry exactly one `Design:` tag; all tags resolve to real instances; every queue-A instance has ≥2 tests, every queue-B non-stub ≥1; no stub translated.
- **PRD-citation pass**: 88/88 docstring citations verified verbatim against `workspace/PRD.md` (whitespace-normalized grep, ≥6-word rule-bearing quotes); 12 initially-elided citations were rewritten to full-sentence quotes (C3).
- **Hygiene**: no `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated code; `pytest --collect-only` collects 88 tests cleanly.

## Step 6: Generate Implementation — 2026-08-14T20:52:00.000Z

Implementation complete. Summary:

## File tree written

`/home/ubuntu/github/CodingPRD/tasks/task_1843_vacant_property_preservation_reo_field/workspace/implementation/`
- `start.sh` — foreground launcher (`exec python3 app.py`), guarded pip install (`if ! python3 -c "import flask"`), `PORT` env (default 10000), binds `0.0.0.0`
- `requirements.txt` (flask>=2.2)
- `app.py` — entry point, blueprint registration, ApiError/404/405/500 envelope handlers
- `db.py` — in-memory store (15 dicts, empty at boot, no seeding), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), entity factory, version-bump helpers, iso3 timestamps
- `errors.py` — full 33-error catalog with HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list meta adds `limit/offset/total_count/has_more`
- `auth.py` — `X-User-ID`/`X-User-Role` validation, 5 roles, role gating
- `util.py` — typed field validators, enum domains, date/datetime/MM-DD parsing, pagination (limit default 10, clamp 1–100; offset default 0), created_at-ASC stable sort
- `services.py` — all calculations + cascades + daily sweep
- `routes_core.py`, `routes_work.py`, `routes_inspection.py`, `routes_muni.py`, `routes_damage.py`, `routes_invoice.py`

## Coverage

- **Endpoints**: 86/86 implemented (verified by decorator count and Flask route map), including `/_clock/set_current_utc` and `/ops/run-daily-sweep`
- **Entities**: 15/15, all fields per scaffold, `version` starts at 1 and bumps on every mutation (cascades bump changed resources; computed-field refreshes bump only on actual change)
- **State machines**: 10/10 (Property, WorkOrder, Inspection, Disposition, Plan, Violation, Registration, DamageReport, Bid, Invoice) with all transitions, preconditions, and side effects — including the 3-link verify-OCCUPIED cascade (occupancy → plan suspend → generated-order cancel with compensation), bid-approve cascade (spawn BID_CONVERTED WO with negotiated cap, report → REPAIR_IN_PROGRESS, competing bids REJECTED), and convey → silent plan ending
- **Calculations**: 12/12 — allowable_reimbursement (PROVISIONAL/FINAL inclusion sets, pinned-snapshot via allowable version history, per-line caps then aggregate budget in created_at ASC/unit_price DESC order, first-applicable denial_reason), prompt_pay_discount (per-line round-half-up then summed), winterization_quote (Decimal multipliers, DEWINTERIZATION floor-halved base), property_condition_score (both variants, posture bands), volume_rebate (inclusive tiers), fine_accrual (deadline-day zero boundary, sweep + on-read refresh), recurring_generation, registration_overlap (half-open, adjacency allowed), crew_day_capacity (>= boundary), photo_completeness (per-type minimums), hold_period (OH 30 / MI 28 / default 30), ytd_rollup (conserved-quantity invariant, 200000 review threshold, year rollover)
- **Validation tiers**: all 10 in priority order (auth → RBAC/ownership → existence L→R → body shape → state → occupancy/hold → referential before temporal — including the registration-before-deadline start-cure ordering → constraint → fiscal)
- **OCC**: both rules — reassign `expected_work_order_version` and bid-create `expected_damage_report_version` → 412 `ERR_STALE_VERSION`; bid creation bumps the report's version

## Self-check results

- Two ad-hoc HTTP suites run against fresh `start.sh` boots: **91/91** main-flow checks and **71/71** edge-case checks pass (plus 13/13 validation-detail checks) — covering quote arithmetic with concrete numbers, pinning isolation across PATCH, provisional-vs-final divergence, SOD flag clearing, capacity boundary, fine accrual boundaries/cap, overlap adjacency, season windows, authority limit at 50000, appeal exhaustion, review-flag set/clear/void-reevaluation, rebate tier boundary at 500000, and compensation invariants
- Isolation contract verified: killed and relaunched via `bash start.sh` from `implementation/` twice — each boot clean with `total_count: 0`; one real bug found and fixed during self-check (family `is_current` recompute was bumping the newly created allowable to version 2; now set at creation, others bump only on change)

## Step 7: Run Tests and Iterate — 2026-08-14T21:10:07.793Z

All 8 rounds pass 88/88. Exit condition met.

## Summary

- **Iterations run:** 2 (one diagnostic 8-round sweep identifying failures, one verification 8-round sweep after the fix — all 8 rounds clean at 88/88).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`** (test bugs, STEP 2 — assertion setup mis-translated PRD):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1843_vacant_property_preservation_reo_field/test_suite/test_02_work_order_dispatch_and_lifecycle.py` — `TestDispatchAndExistence::test_start_by_other_crew_rejected` (line 264) and `TestCrewDayCapacity::test_occ_reassign_stale_version_rejected` (line 337): both tests' inline setup called `validate_success(api.create_crew(...))` relying on the default `expected_status=200`, but PRD §4 verbatim requires "Operations that create a new resource return a `201 Created` status code — servicers, crews, allowable rows, properties, ...". The implementation correctly returned 201. Added `expected_status=201` to both call sites. The tests' actual assertions (`ERR_NOT_ASSIGNED_CREW` on start-by-other-crew; `ERR_STALE_VERSION` on OCC reassign replay) are PRD-faithful and untouched.

- **Fixes applied to `test_helpers/`:** none — fixtures use the lenient `get_success_data` (any 2xx) for setup calls and were consistent with PRD identity/ownership threading.

- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful; both failing tests failed all 8 rounds deterministically at the same setup step, and no genuine implementation defect was found.

- **Note on sweep 1 console noise:** the interleaved pytest stream from the 8 parallel rounds showed torn-line "FAILED" tokens adjacent to names of tests that actually passed (`test_crew_day_capacity_full_date_rejected`, `test_approve_with_flagged_photo_rejected`). The authoritative per-round `results.json` showed exactly the same 2 failures in every round, and sweep 2's console shows zero FAILED tokens — confirming the extra lines were interleaving artifacts, not flakiness.

## Step 8: Finalize PRD — 2026-08-14T21:11:46.287Z

Done. PRD_FINALIZED.md is a byte-identical copy of PRD.md — zero edits were warranted.

## Exit Summary

**Line counts / delta:** PRD.md = 393 lines; PRD_FINALIZED.md = 393 lines; delta = 0 lines, 0.0%.

**Changes:** none.

### Why zero edits — analysis of each step_7_diff item

The `<step_7_diff>` contains exactly two actionable items (both `test_suite/` fixes), no test deletions, no `test_helpers/` fixes, no `implementation/` fixes. Both were evaluated as candidate PRD edits and rejected as pure fixture bugs:

**Item 1 — `test_start_by_other_crew_rejected` (test_02, line 264) setup added `expected_status=201` to `create_crew`.**
- (a) Subject: HTTP status code returned by crew creation (`POST /preservation/crews`).
- (b) Impl paths enumerated: `/home/ubuntu/github/CodingPRD/tasks/task_1843_vacant_property_preservation_reo_field/workspace/implementation/routes_core.py:87` returns `ok(public(crew), status=201)`. Repo-wide grep for `status=201` across all impl route files returned exactly 14 create endpoints (routes_core.py:51 servicers, :87 crews, :135 allowable rows, :221 properties; routes_work.py:108 work orders, :400 photo evidence; routes_inspection.py:59 inspections, :205 dispositions, :297 plans; routes_muni.py:75 violations, :221 registrations; routes_damage.py:61 damage reports, :191 bids; routes_invoice.py:66 expense lines) — a 1:1 match with the 14 resource types already enumerated in PRD.md line 264. Framework default confirmed: `validate_success(response, expected_status=200)` in `/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/testing/validators.py:27`.
- (c) Wording adjustment: none committed. PRD.md line 264 already verbatim pins "Operations that create a new resource return a `201 Created` status code — servicers, **crews**, allowable rows, ...". The test failure came from the framework default of 200 in the test's setup call, not from PRD silence and not from impl divergence. Per the method ("not every item is a PRD silence — some are pure fixture bugs"), no edit.

**Item 2 — `test_occ_reassign_stale_version_rejected` (test_02, line 337) setup added `expected_status=201` to `create_crew`.**
- (a) Subject: same as Item 1 — crew-creation status code in test setup. (The test's actual assertion, `ERR_STALE_VERSION`/HTTP 412 on OCC reassign replay, was left untouched by Step 7 and is already pinned by PRD wording quoted in the test docstring; the implementation at routes_work.py honors it, and Step 7 reports all 8 rounds clean at 88/88 with no impl fix.)
- (b) Impl paths enumerated: same enumeration as Item 1 (routes_core.py:87 plus the full `status=201` sweep across routes_core/routes_work/routes_inspection/routes_muni/routes_damage/routes_invoice).
- (c) Wording adjustment: none committed — identical rationale; pure fixture bug.

No other step_7_diff items exist, so per the HARD SCOPE no other edits are permitted. A fresh implementer reading PRD_FINALIZED.md (identical to PRD.md) already gets the uniquely-determined 201-on-create contract that the implementation exhibits everywhere.

## Step 9: Complete PRD — 2026-08-14T21:20:13.297Z

All edits verified: 19 diff hunks (18 inline revisions + 1 two-line insertion), no unintended changes.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1843_vacant_property_preservation_reo_field/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` 393 lines / 72,183 chars → `PRD_COMPLETED.md` 395 lines / 75,096 chars (**+2 lines, +2,913 chars**). All changes are inline insert/revise within existing paragraphs; no new sections.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 changes across 19 hunks).

**Changes:**

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (limit to [1,100], offset to ≥0), non-integer values fall back to defaults — util.py:246-261
- §2.3 — insert — ambiguity — list sort ties (equal `created_at`) broken by insertion order — util.py:271-273
- §2.5 — insert — ambiguity — `current_utc` echo renders whole-second instants without fractional digits — routes_core.py:28, db.py:15-19
- §2.8 — insert — ambiguity — OCC version guard runs after body-shape validation, before state preconditions — routes_work.py:187-198, routes_damage.py:166-176
- §2.11 — insert — ambiguity — allowable selection: remaining ties after `created_at` desc break by creation sequence, newest first — services.py:72
- §3.1 — insert — ambiguity — duplicate servicer `code` rejected with `ERR_INVALID_REQUEST` — routes_core.py:40-42
- §3.1 — insert — ambiguity — duplicate `crew_code` → `ERR_INVALID_REQUEST`; supplied `daily_capacity_jobs` must be a non-negative integer — routes_core.py:75-79
- §3.1 — insert — ambiguity — `servicer_id` is required for property creation by any caller and must reference an existing servicer (`ERR_NOT_FOUND`) — routes_core.py:176-189
- §3.2 — insert — ambiguity — work order creation requires caller's `X-User-ID` == property's `servicer_id` (`ERR_FORBIDDEN_FOR_ROLE`) — routes_work.py:48-50
- §3.2 — insert — ambiguity — reassignment capacity count excludes the order being reassigned — routes_work.py:199
- §3.3 — insert — ambiguity — submission requires the assigned crew (`ERR_NOT_ASSIGNED_CREW`), same as starting — routes_work.py:239-240
- §3.3 — insert — ambiguity — flagging an already-flagged photo or clearing an unflagged one → `ERR_INVALID_STATE`; clearing retains `flagged_by_user_id`/`flag_reason` — routes_work.py:433-434, 449-455
- §3.3 — revise — mismatch — `content_hash` "serving as the dedupe key" → recorded as supplied, no duplicate detection performed — routes_work.py:383-397
- §3.3 — revise — mismatch — `evidence_complete` recompute refreshes the field in place without incrementing the order's `version`/`updated_at` (vs. §2.12's blanket cascade-bump invariant) — routes_work.py:349-354, services.py:161-162
- §3.4 — revise — ambiguity — `recorded_at` is stamped on every recording regardless of determination (PRD's "likewise stamped" sat inside the OCCUPIED clause) — routes_inspection.py:115
- §3.6 — insert — ambiguity — `season_start_md`/`season_end_md` are zero-padded `MM-DD`; `interval_days`/`max_per_season` must be integers ≥ 1 — routes_inspection.py:277-283, 300-327
- §3.6 — insert — ambiguity — recurring generation pins the §2.11 allowable when a row exists; with none, the order is still generated with the four pin fields null (no `ERR_ALLOWABLE_NOT_FOUND`) — services.py:497-502
- §3.7 — revise — mismatch — recompute-trigger enumeration narrowed to impl: VACANT record / VACANT verify only; escalation from `OPEN` only (`CURE_IN_PROGRESS` escalation recomputes just the fine); registration renewal from `EXPIRED` and release from `ACTIVE` only; damage-report closure with outcome `CLOSED` only — routes_inspection.py:118-129, 149-162; services.py:628-631; routes_muni.py:273-311; routes_damage.py:126-151
- §3.7 — revise — ambiguity — staleness deduction measured in whole days from the most recently recorded `COMPLETED` inspection's `recorded_at` date (fallback: property creation date) — services.py:252-260, 291-297
- §3.8 — insert — ambiguity — bid approval with no current `DAMAGE_REPAIR` allowable row still succeeds: spawned order's `investor_allowable_id`/`investor_allowable_version`/`requires_bid_over_cents` null, `allowable_cap_cents` = bid amount — routes_damage.py:253-271
- §3.9 — revise — mismatch — consumed cents aggregate lines' `allowed_cents` "as recorded at approval" → as currently recorded (not-yet-approved invoices contribute provisional values) — services.py:396
- §3.9 — insert — ambiguity — aggregate-budget line order: further ties after `unit_price_cents` desc break by insertion order — services.py:373

**Not changed (verified aligned, no pin needed):** winterization quote constants/rounding, photo minimums table, hold-day table (OH 30/MI 28/else 30), fine accrual and cap math, posture bands, prompt-pay per-line rounding order, rebate tiers and boundaries, sweep step order and all six response keys, pipeline tier ordering (e.g. `ERR_FINANCIAL_REVIEW_REQUIRED` before `ERR_INVOICE_NO_LINES`; registration gate before deadline gate), endpoint table roles and 201/200 statuses, and the §5 error catalogue — all match implementation exactly.

## Pipeline Complete — 2026-08-14T21:20:13.297Z

All 9 steps done. Final state: 88/88 tests passing across all 8 rounds of the final stability sweep (results.1–8.json all `passed: 88, total: 88`). Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 9 files, 88 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

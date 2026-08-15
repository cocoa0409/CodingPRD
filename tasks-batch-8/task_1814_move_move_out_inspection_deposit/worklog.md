# Worklog — task_1814_move_move_out_inspection_deposit

## Step 1: Create task directory — 2026-08-14T18:16:00.000Z

Directory `tasks/task_1814_move_move_out_inspection_deposit/` and `workspace/` pre-created by the pipeline launcher (Step 1 already done per invocation args).

## Step 2: Generate scaffold — 2026-08-14T19:06:54.686Z

All checks pass. The scaffold is complete and lint-clean. Final state of the deliverables:

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys): scenario, complexity profile (compliance/audit primary + ledger-reconciliation secondary; layers: dual-variant calc, cascading side effects, OCC, ops-run checkpoint; flat topology, cyclic state shape, peer roles, immediate consistency), response envelope, and the seven seed tables.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8).
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9).

**Counts:**
- Entities: **10** (JurisdictionProfile, Property, Unit, Tenancy, Inspection, InspectionItem, DeductionItem, DepositStatement, Dispute, Disbursement)
- State machines: **5** (Tenancy branching w/ auto-transitions + revert, Inspection linear, DepositStatement cyclic DRAFT→ISSUED→DISPUTED→DRAFT + SUPERSEDED, Dispute branching to small-claims, Disbursement branching SENT→CASHED|STALE_DATED→ESCHEATED)
- Calculations: **8** (deposit_interest with ACTUAL_DAYS/WHOLE_YEARS variants, damage_charge with DEPRECIATED/ACTUAL_COST variants, key_fob_lock_charge, statement_totals, small_claims_exposure, court_resolution_settlement, deposit_reconciliation, unit_occupancy_derivation)
- Endpoints: **43** (incl. `POST /pm/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default and `POST /pm/ops/run_daily_cycle` checkpoint)
- Errors: **22** — all exercised by at least one design instance
- Difficulty instances (§1.8): **18** (9 rules × 2), with differentiation honored — dual variants on different domains (deposit interest vs damage charge), combinatorial modes (a) conditional key/fob/lock formula and (b) WHOLE_YEARS per-segment rounding (5,000c vs 5,001c fork), cascades depth 3 (move-out completion) + depth 2 (daily-cycle stale-dating), priority conflicts (state vs temporal; referential vs fiscal), boundaries on days-deadline and carpet-age-in-days via distinct endpoints, cross-entity gates on Inspection→Tenancy and Disbursement→DepositStatement, half-open lease vs closed inspector-window overlap semantics, and compensating invariants on money (cash/reverse) and physical key counts (issue/reopen).
- Corner instances (§1.9): **46** (40 active + 6 `excluded_because` stubs) across all nine guide sections.

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (43 endpoints, 10 entities, 18 §1.8 + 40 §1.9 active instances, 889 calls scanned). Additionally audited: no forbidden concurrency vocabulary, 64 unique instance names across both design files, all `grounds` references resolve, OCC version inputs use `${var}` placeholders/expressions only, and every fixture literal (interest 9,337c/6,000c, carpet 36,400c, paint 60,000c, deadline 2026-08-22, stale threshold 2027-02-06, refund 149,337c, penalty 30,000c, etc.) was precomputed with Python date/arithmetic checks.

**Key design decisions:** late statement issuance marks `late == true` and drives the bad-faith multiplier in small-claims exposure (rather than forfeiture, which would have made deductions undisputable); REFUND disbursements reserve against the balance at creation while PENALTY disbursements bypass it; key/fob/lock charges snapshot counts at move-out completion; one OCC rule (`statement-create-stale-tenancy`, 412) guards the create-with-supersede statement path.

## Step 3: Copy shared files — 2026-08-14T19:07:15.796Z

Copied `./INSTRUCTION.md` → `tasks/task_1814_move_move_out_inspection_deposit/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:15:31.306Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/workspace/PRD.md`.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/workspace/PRD.md` — 255 lines.

**Section overview:**
- **§1 Introduction** (2 paragraphs) — statutory-deadline/liability business framing, lifecycle scope, `/pm` mount.
- **§2 Global Specifications** (10 subsections) — 2.1 RBAC with per-role identity translation (Tenant is `entity_backed:Tenancy`; the other three opaque); 2.2 response envelope emitted byte-identically from `section-2.2-response-structure.md` (verified by containment check); 2.3 pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 common resource properties (`id` UUID no prefix, `created_at`/`updated_at` ISO 8601 UTC 3-fractional-digits, `version`); 2.5 logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`, daily stale-dating sweep with strict-greater aging); 2.6 integer-cents + round-half-up precision; 2.7 the seven-term deposit-ledger invariant; 2.8 OCC (`expected_tenancy_version` → `ERR_STALE_VERSION`/412, statement-create only); 2.9 the ten-step validation pipeline in explicit priority order with left-to-right id resolution; 2.10 jurisdictional rule profiles.
- **§3 Business Logic** (7 subsections, chronological lifecycle grouping) — 3.1 portfolio configuration + occupancy derivation; 3.2 tenancy onboarding, inspection scheduling, item documentation, move-in completion; 3.3 notice and key returns; 3.4 move-out completion with the three-link deduction cascade, depreciation/interest variants; 3.5 statement issuance/deadline/reopen/supersede; 3.6 disputes, counter-offers, small-claims exposure, court settlement; 3.7 disbursements, stale checks, reversal, escheatment.
- **§4 Endpoint table** — 43 rows (matches scaffold's 43 endpoints), 4 columns only.
- **§5 Error catalogue** — 22 rows (matches scaffold's 22 errors), 2 columns only.

**Coverage audit (Hard Contracts):**
- **Contract 1 — Field-name coverage: PASS.** 96 required identifiers (101 entity fields + 65 endpoint inputs + 4 common fields, deduped) all present in backticks; 0 missing. All 50 enum/state values present. All 22 error IDs mentioned in §1–§3 prose. (An initial audit run reported false misses due to regex pairing across fenced JSON blocks; a fence-aware re-audit confirmed full coverage. One genuine gap found and fixed: `COMPLETED` was never backticked.)
- **Contract 2 — Rule coverage: PASS.** Verified per category: 10 validation priorities expressed as an explicit ordered sequence (§2.9); 1/1 OCC rule with write endpoint + `expected_tenancy_version` + `ERR_STALE_VERSION`/412 (§2.8, §3.5); all 24 state-machine transitions across the 5 machines named with preconditions, error IDs, and side effects; all 8 calculations in precise reconstructible prose (both interest variants with pinned rounding order, depreciation residual fraction with zero floor and both charge variants, key/fob/lock conditional branch, statement totals with timeliness boundary "on or before", exposure min-with-cap, court-settlement waterfall, ledger invariant, occupancy derivation); all validation conditions matchable to error IDs; all endpoint side effects expressed; structured field content (defaults, `quantity` = 1, `refund_due_cents` = 0 while `DRAFT`, `statement_seq` per-tenancy from 1) reconstructible; sibling branches (ACTUAL_DAYS/WHOLE_YEARS, DEPRECIATED/ACTUAL_COST, REFUND/PENALTY, CARPET/PAINT/OTHER, both escalation/withdrawal source states) rendered with equal density.
- **Contract 3 — §3 path purity: PASS.** 406 backticked tokens in §3 scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-transition framing and role + action verb.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced at any point.

## Step 5: Generate unit tests — 2026-08-14T19:41:21.191Z

Complete. Summary of the generation for task_1814_move_move_out_inspection_deposit:

## Files written

**test_helpers/** (9 files):
- `types.py` — 10 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` since all entities are `common_fields: true`), 13 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (34 methods incl. clock set + daily cycle)
- `api_errors.py` — `ApiErrorId` (22 errors) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_tenancy_ledger_invariant` (PRD §2.7 identity)
- `factories.py` — 10 payload factories, canonical defaults
- `constants.py` — canonical clock values and expected figures (9,337 / 6,000 / 60,000 / 149,337 / 141,337)
- `test_users.py` — `TEST_USERS` + per-role builders; `make_tenant_headers(tenancy_id)` for the entity-backed Tenant role
- `fixtures.py` — tiered composites: `setup_portfolio`, `setup_occupied_tenancy`, `setup_notice_given`, `setup_vacated_tenancy`, `create_statement_for`, `setup_vacated_with_statement`, `setup_issued_statement_with_damage`, `setup_dispute_on_statement`, `setup_escalated_dispute`, `setup_refund_sent`, `setup_settled_tenancy`
- `__init__.py` — barrel export

**test_suite/** (17 files, conftest.py + 16 test files), 77 tests total.

## Coverage

- **Queue A (Difficulty): 18/18 instances emitted, 0 skipped** — every instance has ≥2 tests (36 tests).
- **Queue B (Corner): 41/41 non-stub instances emitted, 0 skipped** — 41 tests (dispute_window boundary got 2).
- **6 stubs not translated** (tenancy_settlement_bubble_up, err_unit_occupancy_overlap_covered, err_inspector_schedule_conflict_covered, err_statement_not_disputable_covered, err_statement_superseded_covered, immediate_read_after_cascade) — all cross-references verified to resolve to real difficulty instances.

## Skipped instances

None. Every non-stub instance in both queues passed the PRD-first two-condition filter. One instance (`moveout_completion_requires_notice_given`) needed a defensive branch: the PRD gates MOVE_OUT **completion** (not creation) on `NOTICE_GIVEN`, so the test accepts either creation-rejection or completion-rejection while OCCUPIED — preserving unique derivability.

## Audits passed

- All 77 docstrings: exactly one `Design:` tag as the final line; every tag resolves to a real yaml instance; no orphan tags.
- Every test carries ≥1 verbatim ≥8-word PRD quote that survives literal grep of `workspace/PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- No "scaffold"/table/§1.x references in generated code.
- `pytest --collect-only` collects all 77 tests cleanly; all date/money arithmetic independently verified (568-day span → 9,337c ACTUAL vs 6,000c WHOLE_YEARS; carpet age 1,825/1,824 boundary → 0/100c; deadline 2026-08-22; stale threshold 2027-02-06; dispute window 2026-09-09).

## Step 6: Generate implementation — 2026-08-14T19:41:21.191Z

Implementation complete for task_1814 (Move-In/Move-Out Inspection & Deposit Accounting).

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/workspace/implementation/`:

- `start.sh` — guarded launcher (skips pip when Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (Flask entry, error handlers), `db.py` (empty in-memory store — no seeding), `errors.py` (all 22 error IDs with catalog HTTP statuses), `response.py` (envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`), `util.py` (UUIDs, wall-clock `created_at`/`updated_at` with 3-fraction digits, logical clock defaulting to exactly `2026-08-01T00:00:00Z`, integer round-half-up), `middleware.py` (X-User-ID/X-User-Role auth, 4 roles, Tenant entity-backed ownership), `validate.py` (schema checks preceding id resolution per the 10-priority pipeline)
- `routes/`: `clock.py`, `jurisdiction_profiles.py`, `properties.py`, `units.py`, `tenancies.py`, `inspections.py`, `inspection_items.py`, `deductions.py`, `statements.py`, `disputes.py`, `disbursements.py`, `helpers.py` (pagination, Tenant-scoped reads)
- `services/`: `core.py` (ledger recompute from source collections so the §2.7 invariant holds by construction, occupancy derivation, current-statement/projection helpers, settlement evaluation), `calculations.py`

## Endpoint count: 43/43
Including `POST /pm/_clock/set_current_utc` (freely settable both directions — the task's own fixtures move the clock from the 2026-08-01 default back to 2025-01-10 for move-in) and `POST /pm/ops/run_daily_cycle` with strict-greater stale-aging (equality does not stale-date).

## State machines: 5/5
Tenancy (PENDING_MOVE_IN→…→ESCHEATED with automatic SETTLED↔VACATED unwind on reversal), Inspection (DRAFT→COMPLETED + same-kind supersession), DepositStatement (cyclic DRAFT↔ISSUED↔DISPUTED, SUPERSEDED via OCC-guarded create-with-supersede — predecessor's BILLED lines compensate to DRAFT so the new statement re-sweeps, SETTLED bubble-up), Dispute (OPEN/MANAGER_COUNTERED/ESCALATED→CLOSED_AGREED/COURT_RESOLVED/WITHDRAWN), Disbursement (SENT→CASHED/STALE_DATED→ESCHEATED/REVERSED with reservation release and tenancy-ESCHEATED close-out).

## Calculations: 8/8
`deposit_interest` (ACTUAL_DAYS single-rounding and WHOLE_YEARS per-year-round-then-sum; verified 568-day canonical = 9,337c and 6,000c), `damage_charge` (DEPRECIATED residual vs ACTUAL_COST variants; verified carpet 36,400c at residual 364/1825, paint 60,000c, OTHER full replacement), `key_fob_lock_charge` (snapshot counts, conditional lock line), `statement_totals` (deadline/late boundary — issue at noon on deadline day is timely; canonical refund_due 149,337c), `small_claims_exposure` (late × multiplier, cap), `court_resolution_settlement` (auto PENALTY disbursement; verified 30,000c penalty), `deposit_reconciliation` (7-term invariant), `unit_occupancy_derivation`. All money is integer cents with exact-integer round-half-up.

## Boot verification
`bash start.sh` from `implementation/` boots in ~616ms. Verified with fresh processes on dedicated ports: store starts empty (total_count 0 on all collections after reboot), and the full canonical lifecycle was replayed end-to-end post-reboot (move-in → notice → move-out with paint damage → OCC-guarded statement create → issue at 2026-08-10 → deadline 2026-08-22, late=false, refund_due 149,337c → REFUND SENT/reserved → cash → statement SETTLED + tenancy SETTLED, balance 0). ~90 smoke assertions passed across auth/RBAC, all 22 error IDs' happy-path triggers, dispute/escalation/court flows, stale-dating boundary (2027-02-06 exact threshold not stale; 2027-02-07 stale), escheatment to tenancy ESCHEATED, reverse-unwind of settlement, supersede/reopen compensation, ACTUAL_COST/DEPRECIATED and ACTUAL_DAYS/WHOLE_YEARS variants, projection cascades into pre-vacated DRAFT statements, and tenant read-scoping. Note: other agents' test servers are running concurrently on this host — process cleanup was scoped strictly to this task's directory.

## Step 7: Run tests and iterate — 2026-08-14T19:50:07.771Z

# Summary

**Result: clean 8-round parallel sweep — 77/77 tests passing in every round (616/616 total executions, zero flaky failures).**

## Iterations run
2 sweeps (iteration 1: 62/77 per round with 15 deterministic failures; iteration 2 after fixes: 77/77 in all 8 rounds).

## Tests deleted
None. Every failing test traced to a verbatim PRD rule with uniquely derivable outcome; all failures were test-artifact bugs, not PRD-silent assertions.

## Fixes applied to `test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/test_helpers/fixtures.py` — `setup_vacated_tenancy`: default `keys_returned`/`fobs_returned` now resolve to "everything handed back" (issued counts from `tenancy_overrides` or factory `DEFAULTS`) instead of skipping `record_key_return` entirely. Why: PRD §3.2 starts counts at zero and §3.4 mandates KEY/FOB/LOCK lines from unreturned counts, so the old default silently billed 29,500c of hardware charges (10,000 + 7,500 + 12,000) into every canonical-fixture test that expected the no-hardware figures (refund 149,337c; deduction totals 60,000c/68,000c). This single fixture bug produced 13 of the 15 failures (assertions like `119837 == 149337` and `97500 == 68000`). Explicit-count callers (test_01, test_06, test_11, test_13) are unaffected.

## Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/test_suite/test_05_disputes.py` — added missing import `setup_vacated_with_statement` (used at `test_late_statement_creates_penalty_disbursement`, NameError).
- `/home/ubuntu/github/CodingPRD/tasks/task_1814_move_move_out_inspection_deposit/test_suite/test_12_validation_errors.py` — added missing import `setup_occupied_tenancy` (used at `test_return_count_exceeds_issued_rejected`, NameError).

## Fixes applied to `implementation/`
None. The implementation was PRD-faithful on every failing path — the 29,500c hardware charges it billed were exactly what PRD §3.4 requires when no key return is recorded; the fixture was constructing a precondition inconsistent with the tests' documented canonical figures.

## Step 8: Finalize PRD — 2026-08-14T19:52:39.64676690Z

## Summary

**All step_7_diff items are pure fixture/test bugs with no PRD silence and no implementation mismatch. PRD_FINALIZED.md is left as an identical copy of PRD.md.**

### Line counts
- `PRD.md`: 254 lines; `PRD_FINALIZED.md`: 254 lines — 0% delta (byte-identical copy, verified by `diff`).

### Changes
None. Per-item analysis of the `<step_7_diff>`:

1. **`test_helpers/fixtures.py` — `setup_vacated_tenancy` default key/fob returns.** Pure fixture bug, not PRD silence. I verified the behavior the fixture mishandled is uniquely pinned by the PRD and faithfully implemented:
   - PRD §3.2 pins "a new tenancy starts in `PENDING_MOVE_IN` with `keys_returned` and `fobs_returned` at zero" → matches `implementation/routes/tenancies.py:58-59` (`"keys_returned": 0, "fobs_returned": 0` at creation).
   - PRD §3.3 pins absolute running tallies recordable only while `OCCUPIED`/`NOTICE_GIVEN`, with `ERR_RETURN_COUNT_EXCEEDS_ISSUED`, and "the counts snapshotted at move-out completion are the final word" → matches `tenancies.py:108-126` (state guard at :115, exceeds-issued check at :118-121, absolute overwrite at :123-124).
   - PRD §3.4 pins "the missing keys are `keys_issued` minus `keys_returned`", the `KEY_NOT_RETURNED`/`FOB_NOT_RETURNED` quantity/amount formulas, and the `LOCK_CHANGE` condition (at least one missing key AND `lock_change_allowed`, always quantity one) → matches `implementation/services/calculations.py:66-96` verbatim, invoked from the move-out cascade at `implementation/routes/inspections.py:223-234` after the tenancy flips to `VACATED` (inspections.py:200), so the snapshot semantics hold.
   - The old fixture never called `record_key_return`, so the PRD-mandated zero counts legitimately produced the 29,500c of hardware charges (10,000 KEY + 7,500 FOB + 12,000 LOCK). The implementation computed exactly what the PRD requires; the fixture's precondition was inconsistent with the tests' documented canonical figures (refund 149,337c; deduction totals 60,000c/68,000c). Nothing to pin.

2. **`test_suite/test_05_disputes.py` — missing `setup_vacated_with_statement` import (NameError).** Pure test-artifact bug; no behavioral subject, no PRD relevance.

3. **`test_suite/test_12_validation_errors.py` — missing `setup_occupied_tenancy` import (NameError).** Pure test-artifact bug; no behavioral subject, no PRD relevance.

No tests were deleted and no implementation fixes were applied in Step 7, so there are no impl-behavior revelations to pin either.

### Per-edit pre-edit search log
No edits were committed, so no pre-edit searches were triggered. For completeness, the verification searches performed to confirm "no PRD silence" on the single behavioral subject (key/fob/lock counting and charges):
- (a) Subject: key/fob return counting lifecycle and move-out hardware-charge cascade.
- (b) Paths enumerated and read: `implementation/routes/tenancies.py` (full file — create_tenancy :25-77, record_key_return :108-126); `implementation/services/calculations.py` (full file — `key_fob_lock_charges` :66-96, plus interest/damage/deadline helpers for context); `implementation/routes/inspections.py` :150-244 (complete-inspection cascade, the only callsite of `key_fob_lock_charges`, confirmed via grep across `routes/` and `services/`); `test_helpers/fixtures.py` :177-237, 293-330 (the fixed fixture and its downstream consumers).
- (c) N/A — no wording was proposed, since the PRD text at §3.2/§3.3/§3.4 already uniquely determines every enumerated path.

## Step 9: Complete PRD — 2026-08-14T20:00:12.429Z

The patch is complete. Both files are 254 lines (all edits inline, no lines added/removed); character delta is +3,579 (43,844 → 47,423), with 26 paragraphs touched.

## Summary

**Source:** `workspace/PRD_FINALIZED.md` → `workspace/PRD_COMPLETED.md` — 254 lines each; +3,579 chars.

**Counts:** 26 ambiguity-pins, 4 mismatch-revisions (30 changes total).

### Ambiguity-pins (PRD silent → inserted what impl does)

- §2.1 — insert — ambiguity — unrecognized role value fails at role authorization with `ERR_FORBIDDEN_FOR_ROLE`, not header validation — `middleware.py:36-42` (`check_role_allowed` is the only role-value check)
- §2.1 — insert — ambiguity — transitive tenancy-ownership chain for inspection items; Tenant list scoping; profiles/properties/units visible to all roles — `routes/helpers.py:42-75` (`tenancy_scope_of`, `list_response`)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_INVALID_REQUEST` — `routes/helpers.py:18-39`
- §2.3 — insert — ambiguity — `created_at` sort ties break by creation (insertion) order — `routes/helpers.py:81`, `services/core.py:11,22-23` (`_seq`)
- §2.3 — insert — ambiguity — `has_more` = `offset + len(items) < total_count` — `response.py:28`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `services/core.py:21`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` (and `api_request_timestamp`) rendered from host wall clock; logical clock governs only §2.5 business timestamps — `util.py:17-24`, `services/core.py:18-20`
- §2.5 — insert — ambiguity — logical-clock stamps rendered whole-second `YYYY-MM-DDTHH:MM:SSZ`; fractional seconds truncated — `util.py:37-50`
- §2.5 — insert — ambiguity — `stale_dated_disbursement_ids` listed in disbursement creation order — `routes/clock.py:31-47`
- §2.8 — insert — ambiguity — OCC comparison evaluated after tenancy resolution, before state and already-active checks — `routes/statements.py:43-57`
- §2.9 — insert — ambiguity — body must be a JSON object; missing body treated as empty object — `validate.py:11-18`
- §3.2 — insert — ambiguity — `lease_start_on` not strictly before `lease_end_on` → `ERR_INVALID_REQUEST` — `routes/tenancies.py:42-44`
- §3.2 — insert — ambiguity — overlap check considers every tenancy on the unit regardless of status — `routes/tenancies.py:49-56`
- §3.2 — insert — ambiguity — `balance_remaining_cents` initially reads full `deposit_cents` per §2.7 invariant — `routes/tenancies.py:71`
- §3.2 — insert — ambiguity — inspection window with start after end → `ERR_INVALID_REQUEST` — `routes/inspections.py:56-60`
- §3.2 — insert — ambiguity — `linked_move_in_item_id` accepted on items of either inspection kind; only target validity checked — `routes/inspections.py:108,116-118,132-140`
- §3.2 — insert — ambiguity — `replacement_cost_cents`-required check evaluated after the inspection DRAFT-state check — `routes/inspections.py:119-129`
- §3.3 — insert — ambiguity — each key-return write supplies both tallies and may raise or lower them; only issued-count ceiling enforced — `routes/tenancies.py:111-125`
- §3.4 — insert — ambiguity — assessment gate fires before the photo re-check at MOVE_OUT completion — `routes/inspections.py:169-176`
- §3.4 — insert — ambiguity — damage lines created in item creation order with description `Move-out damage: <area_name>`; key/fob/lock lines follow in that order with descriptions `Unreturned keys`/`Unreturned fobs`/`Lock change` — `routes/inspections.py:208-234`, `services/calculations.py:76-95`
- §3.4 — insert — ambiguity — OTHER category charged full replacement even when `actual_repair_cents` documented — `services/calculations.py:48-49`
- §3.4 — insert — ambiguity — interest day count is plain `move_out_on − move_in_on` (move-in day counts, move-out day does not) — `services/calculations.py:23`
- §3.4 — insert — ambiguity — zero-amount manual deduction accepted — `routes/deductions.py:30`
- §3.5 — insert — ambiguity — new statement born with `interest_cents`/`deduction_total_cents`/`released_cents` zero and `issued_at`/`deadline_on`/`late` null — `routes/statements.py:70-83`
- §3.5 — insert — ambiguity — create-with-supersede also reverts the predecessor's BILLED lines to DRAFT with `statement_id` cleared — `routes/statements.py:27-34,60-68`
- §3.5 — insert — ambiguity — issuance checks statement DRAFT state before tenancy VACATED; projections freeze at last draft values — `routes/statements.py:113-120`
- §3.5 — insert — ambiguity — reopen restores projection shadowing from live pending figures — `routes/statements.py:173-180`
- §3.6 — insert — ambiguity — new dispute carries `counter_amount_cents`/`exposure_cents` null until set — `routes/disputes.py:64-72`
- §3.6 — insert — ambiguity — auto PENALTY disbursement made out to `tenant_display_name`, `sent_at` from logical clock — `routes/disputes.py:181-191`
- §3.7 — insert — ambiguity — `ERR_STATEMENT_SUPERSEDED` also covers a statement of another tenancy or a tenancy with no statement — `routes/disbursements.py:42-57`

### Mismatch-revisions (PRD described different behavior → revised to impl)

- §2.5 — revise — mismatch — "may advance the clock" → clock is freely settable in either direction (tests move it backwards) — `routes/clock.py:16-22`, `util.py:66-68`
- §2.9 — revise — mismatch — tenant-ownership leg moved out of priority 2: applied as soon as target tenancy is known (after the existence check that resolves it) — `routes/disputes.py:39-41,116-117,141-142`
- §3.2 — revise — mismatch — `forwarding_address` "may be set until the statement is issued" → supplied at creation only, defaulting to null (no update endpoint exists) — `routes/tenancies.py:38`
- §3.5 — revise — mismatch — reopen "requires an active dispute to exist" → withdraws whatever active dispute rides on the statement (impl has no such precondition guard) — `routes/statements.py:159-164`

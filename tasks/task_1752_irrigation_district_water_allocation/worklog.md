# Worklog — task_1752_irrigation_district_water_allocation

## Step 1: Create task directory — 2026-08-14T13:26:00.000Z

Task directory `tasks/task_1752_irrigation_district_water_allocation/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate scaffold — 2026-08-14T14:20:00.000Z

Scaffold generation complete. All three artifacts are written and pass mechanical lint plus manual rule replay.

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (fixed response envelope, 10 entities, 10 state machines, 2 OCC concurrency rules, 11 calculations, 10-priority validation table, 54 endpoints, 26 error codes, 3 roles). No `scaffold_difficulty_design`/`scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` key; 18 instances, exactly 2 per each of the 9 Difficulty Rules.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` key; 44 active instances across all 9 claim-extraction-guide sections plus 8 `excluded_because` stubs citing §1.8 instances.

**Design summary:**
- **Archetype**: quota/allocation (water ledger per account-season) + temporal windowing (turnout windows, maintenance shutdowns); flat topology, branching state machines, peer roles (DistrictAdmin opaque, DitchRider opaque with `rider_user_id` assignment checks, WaterUser `entity_backed:WaterAccount`).
- **Difficulty anchors**: dual variants in two domains (net-of-committed vs delivered-only water balance on SeasonAllocation; PER_ACRE vs PER_AF_DELIVERED assessment on AssessmentInvoice); combinatorial formulas in modes (a) tiered toll with overage branch and (b) pinned round-per-line-then-sum penalty (568.02 vs 568.01 cent split); cyclic rework loop on RiderWorkOrder + branching lien paths on AssessmentInvoice; depth-3 cascades from two triggers (window activation; drought effectuation with latest-start-first cancellation selector); priority conflicts (state-beats-fiscal, temporal-beats-capacity); inclusive boundaries on available-balance equality and strict-greater delinquency grace; cross-entity gates (TurnoutOrder→WaterAccount lien hold, TransferRequest→DroughtDeclaration freeze); half-open adjacency (windows on CanalReach) vs 6-hour buffered gap (orders per WaterAccount); compensating invariants on committed-af and district-wide transfer volume.
- **Key pinned constants**: AF_PER_CFS_HOUR 0.0826, PRIORITY_CUT_DATE 1914-12-31 (inclusive SENIOR), GRACE_DAYS 10 (strict >), TURNAROUND_MIN_GAP_HOURS 6 (inclusive), LATE_PENALTY_PCT 10, drought stage percentages (STAGE_1 0/15, STAGE_2 10/40, STAGE_3 25/75 senior/junior). All formula-derived asserts were pre-computed as literals (e.g., 5 cfs × 10 h = 4.13 af; tiered toll 1410.00; penalty total 568.02).
- **Testability**: logical-clock endpoint `POST /_clock/set_current_utc` with stated startup default 2026-08-01T00:00:00Z; every FK has a reverse-reachability GET (filtered-list form); OCC rules `order-create-stale-account` and `transfer-create-stale-allocation` with `expected_*_version` always fed from earlier `captures`.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (54 endpoints, 10 entities, 18 §1.8 + 44 §1.9 instances, 567 calls scanned). Instance names unique across both files (71 total, 0 duplicates), scenario string verbatim, no forbidden concurrency vocabulary, all 26 error codes triggerable via validations/transitions and covered by at least one design instance.

## Step 3: Copy shared files — 2026-08-14T14:21:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1752_irrigation_district_water_allocation/workspace/INSTRUCTION.md`. Verified all three scaffold YAMLs exist.

## Step 4: Generate PRD — 2026-08-14T14:27:00.000Z

All three hard contracts pass. Final verification report:

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 66 required, 66 present, 0 missing
- `endpoints[].input` / request-body keys (`to_iso8601`, `expected_water_account_version`, `expected_source_allocation_version`, `due_date`, `rider_user_id`, `measured_cfs`, `measured_hours`, `return_reason`, etc.): all present
- Query params (`limit`, `offset`, `status`, `water_account_id`, `season_id`, `season_allocation_id`, `canal_reach_id`, `turnout_order_id`, `rider_user_id`, `from_account_id`, `to_account_id`): all present
- Response-only keys (`current_utc`, `swept_count`, `delinquent_invoice_ids`, `total_count`, `has_more`): all present

**Contract 2 — Rule Coverage: PASS**
- Validation priority ordering: expressed as the numbered §2.7 list (auth → shape → ownership → existence → stale-version → lifecycle → drought freeze → temporal → uniqueness/capacity → sufficient water), including the note that `to_account_id != from_account_id` is a shape rule under priority 2
- Both `concurrency_rules[]` expressed with write capability + expected-version field + `ERR_STALE_VERSION` (412) in §2.6
- All state-machine transitions expressed with from/to states, preconditions paired to error IDs, and side effects (§3.1–3.9): WaterAccount close gates and lien suspend/reinstate cascades; season announce/open/close with the order+work-order cancellation fan-out and allocation carryover settlement; allocation CURTAILED/ACTIVE flips; turnout-order schedule/reject/cancel/start/verify flows; rider work-order submit/verify/return (including "order remains `FLOWING` on return"); invoice issue/sweep/pay/file-lien; reach SHUTDOWN/IN_SERVICE coupling to window activate/complete; maintenance-window activate cascade; transfer approve/post re-checks; drought effectuate cascade (descending `requested_start_at`, tie-break `created_at` DESC) and non-resurrection on lift
- All calculations expressed as precise prose: `order_quantity` and `measured_delivery` (0.0826 AF per cfs-hour, round half-up 2dp, window hours via seconds/3600), `base_entitlement`, `available_balance` with both net-of-committed and delivered-only variants, `carryover_at_close` (over-allocated forfeit, min-vs-cap with inclusive equality), `curtailed_entitlement` (PRIORITY_CUT_DATE 1914-12-31, stage pairs 0/15, 10/40, 25/75), tiered `water_toll` with overage pool, `assessment_total` (round per line then sum; `LATE_PENALTY_PCT` 10%), `delinquency_determination` (10-day grace, strictly-greater), `turnaround_gap_check` (6-hour gap, exactly-6 allowed), `window_overlap_check` (half-open, adjacency allowed)
- `applies_to` scopes enumerated (drought freeze on transfer create/approve/post; temporal rules across order create/schedule/start and window create/activate; uniqueness rules on season/allocation/invoice creation)
- Sibling-branch symmetry maintained (reject vs cancel paths, pay from three from-states, PER_ACRE vs PER_AF_DELIVERED lines)

**Contract 3 — §3 Path Purity: PASS**
- 359 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. All endpoints referenced via state-transition framing, role + action verb, or capability description.

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation/workspace/PRD.md`

Structure: §1 introduction (2 paragraphs, district-operations angle), §2 with 9 subsections (RBAC with per-role identity prose, verbatim §2.2 envelope, pagination, common properties/precision/ledger principle, logical clock with the 2026-08-01T00:00:00Z startup default, OCC, validation priority, measurement constants, priority classes/drought stages), §3 with 9 workflow subsections (onboarding/season setup, allocation ledger, order placement/scheduling, field delivery, canal maintenance, transfers, drought, billing/liens, closing), §4 four-column endpoint table covering all 43 endpoints, §5 two-column error catalogue covering all 26 error codes. The withheld design index files were not opened or referenced.

## Step 6: Generate implementation — 2026-08-14T15:00:00.000Z

The implementation is complete and verified. 

## Summary

Generated a full Python + Flask implementation for task_1752 (irrigation district water allocation) in `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation/workspace/implementation/`:

**Structure** — `start.sh` (guarded `pip install`, `exec python3 app.py`, PORT env, 0.0.0.0, foreground), `requirements.txt` (flask only), `app.py`, `db.py` (in-memory store, logical clock pinned at 2026-08-01T00:00:00Z, monotonic wall timestamps), `errors.py`, `response.py` (envelope + pagination), `middleware.py` (auth), `validation.py` (shape/existence), `services/` (ledger reconciliation, interval/capacity gates, billing math), and 11 route modules covering all 45 endpoints.

**Key fidelity decisions (PRD wins over scaffold):**
- Maintenance-window conflict (`ERR_WINDOW_TIME_CONFLICT`) is enforced at **schedule only**, not order create — PRD §3.3 enumerates creation gates without it, though the scaffold's priority-8 `applies_to` lists create.
- Rider work order **return** goes `MEASUREMENT_SUBMITTED → IN_PROGRESS` (PRD §3.4 + state machine); the endpoint table's `status := ASSIGNED` side-effect note is contradicted by both.
- Validation order follows PRD §2.7: turnaround gap (priority 8b) before reach capacity (priority 9).
- `ERR_REACH_CAPACITY_EXCEEDED` returns **422** per PRD §5 and the error catalog (the validations table said 409).

**Mechanics:** all AF/money math in `Decimal` with `ROUND_HALF_UP` to 2 places; per-line rounding before invoice totals; half-open interval comparisons to the second; allocation ledger fully recomputed on every mutation with `version` bumped per PRD §2.4 (order create bumps both account and allocation versions, matching the concurrency-rules narrative); drought effectuate cascade-cancels over-committed orders latest-`requested_start_at` first (ties: `created_at` DESC); season close settles `carryover_out_af` on the delivered-only reading with cap-inclusive `min`, forfeited when over-allocated; delinquency sweep uses strict `clock > due_date + 10 days`.

**Verification:** three smoke suites (108 checks total) all passed against fresh-booted servers — auth/RBAC, envelope shape, OCC 412s, turnaround 6-hour boundary, capacity, delivery/verify/return, window overlap/adjacency/activation cascades, transfers with drought freeze, curtailment/lift, PER_ACRE and PER_AF_DELIVERED billing, delinquency boundary, lien suspend/release, season close carryover into next season's `carryover_in_af`, and priority-date SENIOR/JUNIOR boundary at 1914-12-31. `bash start.sh` from `./implementation/` was verified to boot cleanly with an empty store (no seeding) and an instant no-op dependency guard, satisfying the per-test-server restart contract.

## Step 5: Generate unit tests — 2026-08-14T15:01:00.000Z

Test generation complete for task_1752. All output lives under `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation/`.

## What was generated

**Stage 1 — `test_helpers/` (9 files)**
- `types.py` — 10 entity TypedDicts (all `common_fields: true`, so all carry id/created_at/updated_at/version) plus 13 status/role/enum vocabularies.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, including the unprefixed clock endpoint `POST /_clock/set_current_utc`.
- `api_errors.py` — all 26 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions plus `assert_amount` (tight 1e-6 tolerance; a one-cent rounding error still fails) and an allocation-ledger invariant checker.
- `factories.py`, `constants.py` (AF_PER_CFS_HOUR=0.0826, 6h turnaround, 10-day grace, 10% penalty, 1914-12-31 cut date, drought stage percentages), `test_users.py` (opaque admin/rider shared headers + mandatory `make_water_user_headers(account_id)` builder for the entity-backed role), `fixtures.py` (composite setups: open-season+allocation scenarios, order pipeline through DELIVERED, lien-driven suspension, transfer create/post with fresh OCC version reads).
- `__init__.py` barrel re-exporting framework generics + all PRD-specific names.

**Stage 2 — `test_suite/` (conftest + 10 files, 79 tests)**
- Queue A: all 18 difficulty instances get exactly 2 tests each (36 tests).
- Queue B: 42 of 43 non-stub corner instances translated; all 8 `excluded_because:` stubs skipped (cross-references verified resolvable).

## Key adjudication decisions (PRD-first filter)

1. **Skipped** `Corner/entities/create_account_system_fields_input_ignored` — the PRD never states that client-supplied `status`/`version` on create are ignored; a strict-shape implementer could 400 the extra fields. Not uniquely derivable; gap left as a gap (the only non-stub instance not translated).
2. **`drought_effectuation_cascade`** — the instance's "order A survives / committed == 4.13" asserts are NOT uniquely derivable: PRD §3.7's loop condition ("until committed_af no longer exceeds available_af") admits at least three faithful readings (compare against pool vs. dynamic net-of-committed vs. snapshot), yielding cancel-one / cancel-both / cancel-all. The two emitted tests assert only the outcomes all readings agree on: declaration EFFECTIVE, allocation CURTAILED at 6.00 (STAGE_2 junior 40%), latest-start order B CANCELLED, its work order CANCELLED.
3. **`water_account_creation_defaults`** — `version == 1` is not PRD-pinned (§2.4 says version starts at "the value assigned at creation" without naming it), so the test asserts integer type only; status ACTIVE and priority_class SENIOR are asserted verbatim.

## Verification performed
- `pytest --collect-only`: 79 tests, no import/syntax errors; pyflakes clean (barrel-export warnings excepted).
- Design-tag audit: every test ends with exactly one `Design:` line resolving to a real instance; every difficulty instance has ≥2 tests; no stub translated.
- Citation audit: all 79 docstrings contain a quoted span that greps verbatim in `workspace/PRD.md`.
- Recomputed every pinned expected value (order quantities, toll 1410.00, penalty 51.64/568.02, curtailments, carryover caps) with `Decimal` ROUND_HALF_UP — all match the design-index values.

## Step 7: Test/fix iteration loop — 2026-08-14T15:05:00.000Z

All 8 parallel rounds passed cleanly on the first sweep: 79/79 tests in every round, zero failures, zero errors, zero skips. No flakiness surfaced (no test failed in any round), so no diagnostic iteration was needed.

## Summary

- **Iterations run:** 1 (single 8-round parallel stability sweep; all 8 rounds ran to completion with `passed == total` = 79/79 each)
- **Tests deleted:** none — every test in `test_suite/` traces to verbatim PRD prose and all pass against the PRD-faithful implementation
- **Fixes applied to `test_helpers/`:** none — fixtures, factories, and role-header builders were already PRD-consistent (e.g., `make_water_user_headers(account_id)` threads entity-backed WaterUser identity per PRD §2.1; `place_order`/`create_transfer` read fresh versions for the §2.6 OCC fields)
- **Fixes applied to `implementation/`:** none — the existing implementation (Flask, in-memory store, global RLock, Decimal half-up rounding, logical clock starting 2026-08-01T00:00:00Z) satisfied all 79 tests across all 8 concurrent rounds

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation` is green and stable.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T15:05:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T15:30:00.000Z

All edits verified. The file is complete and coherent.

## Summary

**Source vs output:** `workspace/PRD.md` = 289 lines / 43,400 chars → `workspace/PRD_COMPLETED.md` = 289 lines / 48,267 chars (**+4,867 chars, +0 lines** — all changes are inline inserts/revisions within existing paragraphs; no sections added).

**Counts:** 29 changes total — **28 ambiguity-pins, 1 mismatch-revision** (24 diff hunks; some edits share a paragraph line).

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — read (list/get) endpoints enforce role membership only, never ownership-scoping — implementation/routes/orders.py:102-116, invoices.py:57-71 (all list/get use `require_roles` only)
- §2.2 — insert — ambiguity — multi-resource operations return the path-addressed resource (schedule/reject/cancel/start → turnout order; submit/verify/return → work order) — routes/orders.py:155,218, routes/workorders.py:56,78,97
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped (never rejected), non-numeric falls back to defaults; filters are exact-match, unknown query params ignored — implementation/response.py:56-75
- §2.4 — revise — ambiguity — `version` starts at 1; a call recomputing an allocation's ledger bumps its version exactly once per call regardless of how many fields/cascaded records change — implementation/db.py:102-114, services/ledger.py:82-87, routes/droughts.py:96-111
- §2.4 — insert — ambiguity — datetime inputs: naive read as UTC, sub-second truncated; domain datetime fields rendered second-precision `Z` — implementation/db.py:78-99, response.py:24-25
- §2.5 — revise — ambiguity — clock set applies the supplied instant verbatim, earlier or later (no monotonicity check) — implementation/routes/clock.py:12-18
- §2.5 — insert — ambiguity — all state in memory; store starts empty each boot, nothing seeded — implementation/db.py:25-41
- §2.7 item 2 — revise — ambiguity — shape validation also rejects undeclared body fields and missing/non-object bodies where required fields exist — implementation/validation.py:24-31,65-77
- §2.7 item 3 — insert — ambiguity — ownership checks against body fields (order/transfer create) run before existence; ownership checks reading a stored field of a path-addressed resource (cancels, pay, start, submit) run immediately after that resource's 404 check — routes/orders.py:50-52 vs 179-182, workorders.py:44-47, invoices.py:96-99, transfers.py:188-191
- §2.9 — insert — ambiguity — priority-class comparison is by calendar date (any instant on 1914-12-31 → SENIOR) — routes/accounts.py:29-31
- §3.1 — insert — ambiguity — allocation create outside ANNOUNCED/OPEN → `ERR_SEASON_NOT_OPEN`; no account-status precondition — routes/allocations.py:45-49
- §3.1 — insert — ambiguity — new allocation's `carryover_out_af` null until season close; all ledger sums 0.00 at creation — routes/allocations.py:54-65
- §3.3 — insert — ambiguity — order create does not require the named allocation to belong to the named account — routes/orders.py:53-80 (no coherence check present)
- §3.3 — revise — ambiguity — order born with `actual_delivered_af` null and `over_delivered` false — routes/orders.py:92-94
- §3.3 — revise — ambiguity — work order born with `measured_cfs`/`measured_hours`/`measured_af`/`return_reason` all null — routes/orders.py:144-153
- §3.4 — insert — ambiguity — starting a non-`SCHEDULED` order → `ERR_INVALID_ORDER_STATE` — routes/orders.py:202-204
- §3.4 — insert — ambiguity — resubmission after a return overwrites measured values but retains the recorded `return_reason` — routes/workorders.py:51-56,91-94
- §3.5 — insert — ambiguity — window planning imposes no reach-status precondition; `reason` defaults to null — routes/windows.py:24-51
- §3.6 — insert — ambiguity — source allocation must exist at creation (else `ERR_NOT_FOUND`); destination allocation not consulted at create or approve — routes/transfers.py:74-76
- §3.6 — revise — ambiguity — posting requires the destination allocation to exist, checked after the source-balance re-check (else `ERR_NOT_FOUND`) — routes/transfers.py:157-161
- §3.7 — insert — ambiguity — declaration proposal has no season-state precondition; multiple concurrent `PROPOSED` declarations allowed — routes/droughts.py:30-46
- §3.7 — revise — ambiguity — curtailment cascade also stops when no `REQUESTED`/`SCHEDULED` candidates remain; `FLOWING` orders are never cascade-cancelled — routes/droughts.py:99-110
- §3.8 — insert — ambiguity — invoice creation has no account-status or season-status precondition — routes/invoices.py:24-54
- §3.8 — insert — ambiguity — `PER_AF_DELIVERED` with no allocation for the pair: delivered volume and pool read zero, toll line 0.00 — services/billing.py:21-27
- §3.8 — revise — ambiguity — `due_date` is null while `DRAFT` (alongside `issued_at`/`paid_at`) — routes/invoices.py:46-50
- §3.8 — revise — ambiguity — sweep applies regardless of season lifecycle state; `delinquent_invoice_ids` reported in `created_at` ascending order — routes/seasons.py:146-166
- §3.8 — revise — **mismatch** — lien-release on payment restores `ACTIVE` only while the account is still `SUSPENDED`; an account closed in the interim remains `CLOSED` (PRD previously said "returns to ACTIVE" unconditionally) — routes/invoices.py:107-115
- §3.9 — revise — ambiguity — account closure is blocked by a `PENDING`/`APPROVED` transfer naming the account as source **or** destination — routes/accounts.py:74-78
- §4 — insert — ambiguity — undeclared path or unsupported method → `ERR_NOT_FOUND` (404) in the standard envelope — implementation/app.py:35-42

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1752_irrigation_district_water_allocation/workspace/PRD_COMPLETED.md`

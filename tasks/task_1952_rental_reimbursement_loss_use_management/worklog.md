# Worklog — task_1952_rental_reimbursement_loss_use_management

## Step 1: Create Task Directory — 2026-08-15T02:53:58.000Z

Directory `tasks/task_1952_rental_reimbursement_loss_use_management/` and `workspace/` pre-created by pipeline launcher (Step 1 marked ALREADY DONE by invocation args). Difficulty directive from user: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-15T03:39:22.000Z

All three scaffold artifacts are complete, lint-clean, and verified.

**Files written** (task dir: `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/`)
- `SCAFFOLD.yaml` — 1613 lines (§1.0–§1.7 only)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 915 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1294 lines (single key `scaffold_corner_design`)

**Surface counts**: 14 entities, 10 state machines (incl. append-only records), 8 calculation rules, 13 validation priority tiers, 63 endpoints, 46 error codes, 8 roles, 2 OCC concurrency rules, logical clock endpoint with mandated 2026-08-01T00:00:00Z default.

**Test design counts**: §1.8 = 22 non-stub instances (every rule ≥2; combinatorial_formula, non_linear_state_machine, boundary_precision, cross_entity_state_dependency each have 3). §1.9 = 56 non-stub + 14 `excluded_because` stubs, spanning all nine claim-extraction-guide sections. 911 calls scanned by `scaffold_lint.py` → `VERDICT: clean lint`; zero unbound `${var}` placeholders; all stub refs resolve.

**Notable design decisions**:
- Flat topology (no URL nesting, FK-filter lists + sub-resource GETs), segregation-of-duties role model (ClaimsAdjuster verifies/audits, SettlementApprover settles/pays — cross-denied both ways), parallel Claim state dimensions (rental × loss-of-use tracks).
- Hard corners: provisional (uncapped, pre-tax) vs audited (per-day limit-capped, per-day half-up tax rounding pinned over sum-then-round, fee cap) charge divergence; circular extension-grant evaluation order pinned to pre-grant values; half-open reservation overlap vs deliberately CLOSED LOU-conflict semantics vs aggregate per-day fleet capacity (three distinct interval semantics); 3-hop delay-milestone cascade (milestone → repair order → reservation → comm log) and dispute→recovery→balance cascade.
- Per §1.2.1's serial-observability filter I dropped an initially-planned invoice-audit OCC rule (second decision is already rejected by the MANUAL_REVIEW state precondition) — only the two true create-with-supersede races (verification create, extension create) carry OCC.
- All formula-derived asserts pre-computed to literals (verified via Python): 52500/59200 divergence, 24405 vs 24403 rounding delta, grant values 4/5/10, reserve 53200, recovery 12000 = 5000+7000+0.

(Note: first scaffold subagent turn ended after writing SCAFFOLD.yaml only; resumed via SendMessage to complete the two design-index files, including a YAML flow-mapping quoting fix for JSONPath captures.)

## Step 3: Copy Shared Files — 2026-08-15T03:39:22.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1952_rental_reimbursement_loss_use_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T03:57:08.000Z

The PRD is complete and all audits pass. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/workspace/PRD.md` — 357 lines

**Sections:**
- §1 Introduction (2 paragraphs: business context + segregation-of-duties/ledger/clock framing)
- §2 Global Specifications — 2.1 RBAC (8 roles, identity prose per role), 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination, 2.4 Logical Clock & Calendar-Day Arithmetic, 2.5 Common Resource Properties & Monetary Precision (incl. the 3 append-only entities without `updated_at`/`version`), 2.6 Claim Financial Ledgers (reserve/day-cap/recovery formulas + conservation invariants), 2.7 Validation Order & Error Precedence (13-rung ladder, `ERR_INVALID_REQUEST` after-existence pinning, state>fiscal and temporal>referential pairs, 402-vs-409 fiscal split), 2.8 Nested Resource Retrieval (12 typed 404s, left-to-right), 2.9 Ownership & Segregation of Duties, 2.10 OCC, 2.11 Automated Cascades
- §3 Business Logic — 9 subsections: desk bootstrap, claims intake & coverage verification, repair orders & the 3-hop delay cascade, booking/authorization, extensions & class changes, return & unnecessary-day assessment, loss-of-use, invoicing/audit/settlement, recovery & final settlement
- §4 Endpoint table — 63 rows, 4 columns only
- §5 Error catalogue — 48 rows, 2 columns only; document ends there (no audit footer)

**Self-audit results (all PASS):**
- **Contract 1 (field-name coverage):** entities[].fields 85/85 present, endpoint request-body extras 5/5, query params 7/7 — 0 missing across two passes (first pass had a measurement artifact from ``` fences breaking naive backtick pairing; corrected by stripping fenced blocks before extraction)
- **Contract 2 (rule coverage):** 93/93 rule-phrase spot-checks present — all 37 state transitions with preconditions/error-ids/side-effects, all 9 calculations in precise reconstruction-safe prose (half-open vs CLOSED day counts, uncapped pre-tax provisional estimate, pinned per-day half-up tax rounding with 8% rate and 2,500-cent fee cap, pinned extension-grant evaluation order with 1-day completion grace, downgrade/upgrade cost split, both LOU payout variants, 1-day return grace with empty-set boundary, reserve/day/recovery reconciliation invariants), both OCC rules fully expressed, all 13 validation priorities with ordering, all 48 error ids mentioned in §2/§3 prose, sibling branches (verify branches, approve/deny, 3 audit decisions, payment/waive) at equal density
- **Contract 3 (§3 path purity):** 536 backtick tokens scanned, 0 path/method violations

**Judgment call reported for transparency:** the scaffold's reservation-create endpoint lists `expected_claim_version` in its input and declares "OCC on Claim.version" while the concurrency_rules/validation-rung-9 tables name only the verification and extension creates; the PRD carries the field on booking and describes it as an OCC anchor rejected with `ERR_STALE_VERSION` (HTTP 412), consistent with the endpoint's own declared contract.

## Step 5: Generate Unit Tests — 2026-08-15T04:29:03.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (10 modules, all under `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/test_helpers/`):
- `types.py` — 14 entity TypedDicts (append-only RepairMilestone/ClassChangeRecord/CommunicationLog correctly omit `updated_at`/`version` per PRD §2.5), 16 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~45 methods)
- `api_errors.py` — 48 `ApiErrorId` members + HTTP status map, registered via `set_error_http_status_map` (incl. the 402/409 fiscal split and 412 OCC)
- `assertions.py` — per-entity assertions + `assert_recovery_case_conservation` + `assert_timestamp_matches_clock` (instant-compare, so PRD-unpinned string formatting is never asserted)
- `factories.py`, `constants.py` (tax rate 8%, fee cap 2500, both grace days, canonical 6000/20/3500 claim terms)
- `test_users.py` — opaque-role constants + mandatory per-instance builders for the three entity-backed roles (Customer/RepairShop/RentalPartner)
- `fixtures.py` — composite builders: `setup_verified_claim_context`, `setup_authorized/active/returned_rental_scenario`, `setup_pending_extension_scenario`, `setup_overstay_recovery_scenario`, `setup_manual_review_invoice_scenario`, `setup_auto_approved_invoice_scenario`, `setup_lou_submitted_scenario`, etc., with OCC versions always re-read via GET before create calls and entity-backed headers threaded by real entity id

**`test_suite/`**: `conftest.py` + 10 numbered test files (bootstrap, verification, repair/milestones, booking, lifecycle, extensions, class changes, invoices, loss-of-use, recovery/settlement).

## Test counts
- **100 tests total**: Queue A (Difficulty) **44** = 22 instances × 2; Queue B (Corner) **56** = 56 non-stub instances × 1.
- **0 skipped instances.** Every difficulty and non-stub corner instance passed the PRD-first two-condition filter — this PRD renders every scaffold rule in verbatim prose (including both pinned precedence pairs in §2.7 and the pinned rounding order in §3.8).
- All 14 corner `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves to a real §1.8 instance name.

## Judgment calls (assertion tightening under the two-reader rule)
- Dropped the `version == 1` literal from `claim_creation_applies_computed_defaults` (PRD never pins the initial version value; all other asserted defaults kept).
- `rate_card_snapshot` asserted as a 3-key dict without pinning key names (PRD pins the field name and "the partner's three class rates", not the key spelling).
- Clock-stamped fields (`reported_at`, `sent_at`) asserted by parsed-instant equality, not string equality (PRD pins the instant, not the serialization).
- `reservation_create_body_fk_not_found` built with a real repair order and only the `claim_id` bogus, so `ERR_CLAIM_NOT_FOUND` is the unique PRD-derivable outcome (PRD pins left-to-right ordering only for path ids, not body-FK iteration order).

## Self-check results
- **Stage 1**: all helpers compile; package imports cleanly standalone; 48 errors registered.
- **Stage 2 completeness audit** (scripted): 100 tests, every docstring ends with exactly one `Design:` line; all 100 tags resolve to real instances; no tag points at a stub; difficulty shortfall = 0, corner shortfall = 0.
- **Final PRD-citation pass** (scripted): all 138 quoted citation spans across the 100 docstrings survive whitespace-normalized literal grep of `PRD.md`; every asserted `error_id` is named in PRD prose with its trigger; the two priority-pair tests cite §2.7's explicit pinning sentences.
- **No** `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings; `pytest --collect-only` collects exactly 100 tests with zero import errors.

## Step 6: Generate Implementation — 2026-08-15T04:29:03.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/workspace/implementation/`)

- `start.sh` — guarded installer (`pip install` only if `import flask` fails) then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, `ApiError` handler, process-wide WSGI lock, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dicts (14 entity tables) + logical clock initialized to `2026-08-01T00:00:00Z`; no seeding
- `errors.py`, `response.py`, `middleware.py`, `util.py` — envelope/error/pagination/auth/date/Decimal-tax helpers
- `services.py` — derived claim ledgers, audited-charge algorithm, auto-adjudication fork, fleet capacity, cascades
- `routes_*.py` (10 modules) — all endpoints

**Endpoint count: 63/63** from the PRD §4 table.

## Verification

Two self-written end-to-end smoke suites (~140 assertions) both pass on fresh boots, covering: envelope shape, auth rungs, uniqueness, OCC (412) on both guarded creates, the delay cascade (order estimate → reservation EXTENSION_REVIEW → EXPECTATION_SET comm → claim version), extension approve/deny with the pinned grant order, class-change cost splits (downgrade / waived / unwaived upgrade), provisional-vs-audited divergence with per-day ROUND_HALF_UP tax (verified the summed-rounding invoice routes to MANUAL_REVIEW), auto-adjudication, dispute → RecoveryCase → settle gating, overstay recovery, LOU closed-interval conflicts both directions, both LOU payout variants, SoD (adjuster cannot pay), claim settle/close gating, pagination clamping. Also verified the `bash start.sh` contract: fresh process boots with an empty store and the clock reset.

## Design decisions / PRD ambiguities resolved

1. **Derived ledgers computed, not stored**: `rental_reserve_cents`, `authorized_days_total`, `recovery_balance_cents`, `audited_charge_cents` are computed live from child state per the reconciliation formula — conservation invariants (authorize/cancel neutrality, estimate→settled reclassification) then hold by construction. `estimated_charge_cents` is stored and mutated (class-change deltas use capped rates and only remaining days, so it is not derivable).
2. **Authorize gate order**: PRD §2.7 ladder puts fleet capacity (rung 12) before fiscal (rung 13), but §3.4 prose and the scaffold state machine both pin reserve → cap → fleet. I followed the workflow-specific order (reserve 402 → cap 409 → fleet 409).
3. **Extension approve order**: followed the PRD-pinned evaluation sequence exactly — state checks → cap headroom (409) → days_needed (ERR_EXTENSION_NOT_JUSTIFIED) → grant cost vs reserve (402) → fleet re-check.
4. **Overstay projection at repair completion**: formula for the projection is undefined (actual_return_date is null). I project with the authorized window end: `max(0, authorized_return_date − (actual_completion_date + 1 grace))`, matching the field description "0 when repair not COMPLETED" and making the side effect meaningful.
5. **Delay cascade comm log**: created unconditionally on the order's claim (PRD: "the claimant hears about the slipped timeline") even when no ACTIVE reservation exists; claim version always bumps.
6. **Booking gate literalness**: rung 7 requires `rental_track_status == COVERAGE_VERIFIED` verbatim, so a claim whose track advanced to RENTAL_ACTIVE rejects further bookings — implemented as written.
7. **Verification decide on an advanced track**: the track mapping applies only from OPEN (the state machine defines no other origin), preventing a late decision from dragging the track backwards.
8. **DISPUTED invoice settle**: `audited_payable_cents` stays null on dispute; settle treats it as 0 for the reserve/audited sums ("same reserve reconciliation" over a null payable).
9. **LOU deny `decision_reason`**: accepted as input but not persisted — the entity schema has no such field.
10. **Pagination**: `limit < 1` or negative/non-integer pagination params → `ERR_INVALID_REQUEST`; `limit > 100` clamped to 100.
11. Internal-only keys (`_seq`, `_initial_class`, `_recovery_case_id`) are stripped by the serializer so no non-PRD fields leak into responses.

## Step 7: Run Tests and Iterate — 2026-08-15T04:38:53.000Z

All 8 rounds verified clean on disk: 100/100 passed, 0 failed, 0 errors in every round. The task is complete.

## Summary

**Iterations run:** 2 (initial 8-round diagnostic sweep → fix → verification 8-round sweep; a redundant confirmation sweep also ran to completion against the same fixed code, all rounds clean).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none — the helpers were correct.

**Fixes applied to `test_suite/` (STEP 2 test-artifact bug):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/test_suite/test_09_loss_of_use.py` — the helper methods `TestLouPayoutVariantDivergence._setup_two_variants` and `TestClaimParallelTracks._setup_lou_denied_with_active_rental` called `api.attach_lou_documentation(...)` / `api.deny_loss_of_use_claim(...)` using the bare name `api`, which is the session-scoped pytest fixture and is only in scope inside test-method signatures, not plain helper methods. All 4 dependent tests (`test_standard_per_diem_payout`, `test_comparable_vehicle_payout`, `test_lou_track_progresses_independently`, `test_rental_track_untouched_by_lou_denial`) failed in every round with `NameError: name 'api' is not defined`. Fixed by switching the three calls to the already-imported module-level `api_client`, matching the convention used by helpers elsewhere in the suite (e.g., `test_04` uses `api_client.suspend_rental_partner`). No assertion was altered — the PRD-cited rules (§3.7 payout variants, §3.2 parallel-track independence) remain fully asserted.

**Fixes applied to `implementation/`:** none — the implementation was never reached by the failing tests (the NameError fired in test setup before any API call), and all other 96 tests passed against it from the start.

Final state: 8/8 rounds at 100/100 passed under `per-test-server` isolation (verified by orchestrator against results.1.json … results.8.json on disk).

(Note: the subagent's first turn ended while the verification sweep was still in flight; it was resumed via SendMessage and collected all 8 results files before emitting this summary.)

## Step 8: Finalize PRD — 2026-08-15T04:40:54.000Z

Done. PRD_FINALIZED.md is in place and is byte-identical to PRD.md — the correct outcome for this Step 7 diff.

## Analysis

The single Step 7 item was a pure Python test-harness bug in `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/test_suite/test_09_loss_of_use.py`: helper methods `_setup_two_variants` and `_setup_lou_denied_with_active_rental` referenced the session-scoped fixture name `api`, which is only bound inside test-method signatures. The `NameError` fired during test setup, before any API call, so the implementation was never even reached. The fix swapped three calls to the module-level `api_client` import; no assertion was changed, and all 4 previously-failing tests then passed against the unchanged implementation.

Tracing this to the PRD:
- The behavior under test is pinned verbatim by PRD §3.7 (PRD.md line 208): `STANDARD_PER_DIEM` payout = `loss_of_use_per_diem_cents × billable_days` ignoring claimed amount; `COMPARABLE_VEHICLE` = lesser of `claimed_amount_cents` and `coverage_daily_limit_cents × billable_days`, with billable days = closed-interval count capped at `coverage_duration_cap_days`. This matches `implementation/routes_lou.py:133-140` exactly.
- PRD §3.2 (PRD.md line 152) pins parallel-track independence, and `routes_lou.py` `deny_lou` (lines 148-163) touches only `loss_of_use_track_status`, never `rental_track_status` — matching.

A fresh implementer reading the PRD learns nothing from which Python identifier a pytest helper uses. Zero PRD silences, zero PRD/impl mismatches follow from this diff item.

## Summary

- **Line counts:** PRD.md 357 lines, PRD_FINALIZED.md 357 lines — 0% delta (`diff` confirms identical).
- **Changes:** none.
- **Per-edit pre-edit search log:** no edits were committed, so no (a)/(b)/(c) entries apply. For completeness, the analysis that produced the zero-edit decision:
  - Subject: LOU payout variants and parallel-track independence cited by the fixed tests.
  - Impl paths enumerated and read: `implementation/routes_lou.py` in full (create/attach/approve/deny/pay handlers, lines 30-181, including payout math at 133-140 and deny at 148-163); PRD.md §3.2 (line 152), §3.7 (lines 202-208); test helpers in `test_suite/test_09_loss_of_use.py:177-280`; `grep` over `implementation/services.py` and `routes_lou.py` for `payout_cents`/`per_diem`/`daily_limit` to confirm no other payout path exists.
  - Conclusion: every behavioral claim the fixed tests assert is already pinned verbatim in the PRD and matches the implementation; the Step 7 fix changed only test-harness mechanics, so no PRD wording change is warranted.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1952_rental_reimbursement_loss_use_management/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

## Step 9: Complete PRD — 2026-08-15T04:47:11.000Z

The document is complete and well-formed. 

## Summary

**Source**: `PRD_FINALIZED.md` (byte-identical to `PRD.md`), 357 lines → `PRD_COMPLETED.md`, 359 lines; char-delta **+2359**.

**Counts**: 12 ambiguity-pins (inserts), 1 mismatch-revision (extension-approve precondition order). No new sections; all changes are inline inserts/revisions within existing paragraphs.

### Changes

- **§2.3 Pagination** — insert — ambiguity — pinned that non-integer or `<1` `limit` and non-integer or negative `offset` fail with `ERR_INVALID_REQUEST` (400), while `limit>100` is silently clamped; also pinned creation-order tie-break in list sorting — `implementation/response.py:23-51`, `implementation/services.py:45-46`.
- **§2.5 Common Resource Properties** — insert — ambiguity — pinned that stored fields whose names begin with `_` are internal and stripped from every API response body — `implementation/services.py:41-42`.
- **§2.11 Automated State Cascades** — insert — ambiguity — pinned that the all-reservations-terminal condition for `RENTAL_ACTIVE → RENTAL_CLOSED` is evaluated at reservation close only; a cancellation that leaves every reservation terminal does not by itself advance the track — `implementation/services.py:338-347`, `implementation/routes_reservations.py:251,255-267`.
- **§3.2 Coverage Verification** — insert — ambiguity — pinned that the decide-time rental-track mapping applies only when the track is still `OPEN`; a decision on an already-advanced track leaves `rental_track_status` unchanged — `implementation/routes_verifications.py:87-91`.
- **§3.3 Repair Orders** — insert — ambiguity — pinned the overstay-projection formula at repair completion: `unnecessary_days = max(0, authorized_return_date − (actual_completion_date + 1 grace day))`, recomputed per `ACTIVE`/`EXTENSION_REVIEW` reservation with each such reservation's `version` incrementing, and no claim-state touch — `implementation/routes_repair.py:122-129`.
- **§3.3 Delay Cascade** — insert — ambiguity — pinned that the `EXPECTATION_SET` communication is created on every accepted delay report, even when no `ACTIVE` reservation existed to flip — `implementation/routes_repair.py:177-184`.
- **§3.5 Extension Approval** — revise — mismatch — PRD prose listed state preconditions as reservation → request → repair order; impl checks request `SUBMITTED` → reservation `EXTENSION_REVIEW` → repair order `IN_PROGRESS`, ahead of any computation; prose reordered and the ordering pinned — `implementation/routes_extensions.py:119-128`.
- **§3.7 LOU Conflict Rule** — insert — ambiguity — pinned that the reservation window endpoints for conflict are `pickup_date` and `authorized_return_date` (both counted), and that the loss-of-use claim's own status is ignored (even `DENIED`/`PAID` records still conflict) — `implementation/routes_reservations.py:91-96`, `implementation/routes_lou.py:66-73`.
- **§3.7 LOU Denial** — insert — ambiguity — pinned that `decision_reason` on denial is accepted as input but not persisted (the LOU record has no such field) — `implementation/routes_lou.py:155`.
- **§3.8 Invoice Fork** — insert — ambiguity — pinned that `unauthorized_days` is computed at ingestion for every invoice (necessarily zero for auto-approved ones), not only for manual-review ones — `implementation/routes_invoices.py:86-87`.
- **§3.8 Audited Final Algorithm** — insert — ambiguity — pinned that two class changes sharing the same `effective_date` resolve in favor of the later-recorded change — `implementation/services.py:258-267`.
- **§3.8 Audit Decision** — insert — ambiguity — pinned that `DISPUTE_UNNECESSARY_DAYS` leaves `audited_payable_cents` null — `implementation/routes_invoices.py:138-145`.
- **§3.8 Invoice Settlement** — insert — ambiguity — pinned that a settled `DISPUTED` invoice still carries null `audited_payable_cents`, contributing zero to the reserve's settled-actuals term and to the reservation's `audited_charge_cents` — `implementation/routes_invoices.py:161-173`, `implementation/services.py:155,169-171`.

### Known judgment calls verified as already pinned (no change needed)
- Derived-vs-stored ledgers: §2.6 already says "derived ledgers"; impl derives at read (`services.py:145-185`) — consistent.
- Authorize gate order reserve → cap → fleet: §3.4 prose order already matches impl (`routes_reservations.py:157-168`).
- Booking gate requiring `rental_track_status == COVERAGE_VERIFIED` literally (advanced track rejects bookings): §3.4 "its rental track must be `COVERAGE_VERIFIED`" already pins it (`routes_reservations.py:58-60`).

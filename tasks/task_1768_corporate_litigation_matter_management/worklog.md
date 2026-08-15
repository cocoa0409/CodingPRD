# Worklog — task_1768_corporate_litigation_matter_management

## Step 1: Create Task Directory — 2026-08-14T14:44:54.000Z

Task directory `tasks/task_1768_corporate_litigation_matter_management/` and `workspace/` subdirectory pre-created and pre-assigned by pipeline launcher (Step 1 DONE per invocation instructions). Index not recomputed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T15:56:29.000Z

## Summary

Generated the complete scaffold for **task_1768_corporate_litigation_matter_management** from the verbatim scenario, per the prd-bench-scaffold-generator skill spec. All three files are written and pass `scaffold_lint.py` with a clean verdict (1051 calls scanned across 62 active design instances, 0 violations).

**Files:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Counts:**
- Entities: 14 (Matter, StaffUser, CounselFirm, Engagement, Budget, AccrualEntry, LitigationHold, HoldCustodian, DiscoveryVendor, VendorWorkOrder, Deadline, SettlementAuthorityPolicy, SettlementRequest, PaymentRequest)
- State machines: 12 (66 transitions total; includes parallel payment-rail dimension on PaymentRequest and compound hold↔custodian bubble-up)
- Calculations: 9 (3 with dual variants)
- Endpoints: 109 (66 POST, 41 GET, 2 PATCH) — includes the mandated `/_clock/set_current_utc` with the fixed 2026-08-01T00:00:00Z default
- Error catalog: 28 codes, all referenced by validations/concurrency rules
- Validations: 29 priority-ordered rules; RBAC: 8 roles (segregation-of-duties model, entity-backed StaffUser identities, opaque BoardCommittee)
- §1.8 difficulty instances: 18 (2 per rule × 9 rules, each with full structured setup_api_calls)
- §1.9 corner instances: 52 (44 active + 8 excluded_because stubs citing §1.8 coverage)

**Notable design decisions:**
- **Posture-driven gating** via a pinned precedence ladder (jurisdictional-miss FROZEN > resolved FROZEN > status RESTRICTED > budget-utilization thresholds at 90/100), which gates work-order, accrual, hold, and settlement operations.
- **Dual-variant difficulty anchors**: exposure-tier classification (midpoint vs conservative high-end by matter_type, verified divergent at low=1M/high=101M/prob=100 → TIER_2 vs TIER_3) and reserve recognition (provisional/post-resolution/reopened variants); work-order cost pins floor-per-tier rounding (gb=102 @ 1013¢ → 102920 vs naive 102921).
- **OCC** on `expected_matter_version` guards budget and settlement creation (two true create-with-supersede races); all test recipes capture fresh versions via GET immediately before OCC calls.
- **Segregation of duties** enforced by X-User-ID comparison (submitter≠approver on budgets/payments, requester≠approver on settlements, owner≠approver on LEAD_COUNSEL engagements) with dedicated `ERR_SEGREGATION_OF_DUTIES`.
- **Cascade ordering pinned** within matter resolution (work orders cancel → holds release → custodians release → deadlines vacate) so the hold-pin check is vacuous on the system path.
- All formula-derived asserts use literals I computed by executing the formulas (tier boundaries, utilization floors, reserve arithmetic, tiered work-order costs).

Orchestrator verification: all three files exist, parse as YAML, and `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` keys.

## Step 3: Copy Shared Files — 2026-08-14T15:57:12.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1768_corporate_litigation_matter_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T16:23:24.000Z

PRD generation is complete and all three hard contracts pass. Final summary:

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/workspace/PRD.md` — 390 lines.

## Section list

- **§1 Introduction** (2 paragraphs: business context + design commitments)
- **§2 Global Specifications** — 2.1 RBAC (8 roles + identity binding), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity and Change Tracking (incl. AccrualEntry's `id`/`created_at`-only exception), 2.5 Money/Integer Arithmetic/Rounding, 2.6 Logical Clock and System Sweeps, 2.7 Version-Guarded Writes (OCC), 2.8 Segregation of Duties, 2.9 Matter Posture Ladder, 2.10 Nested Paths and Reference Integrity, 2.11 Validation Evaluation Order (all 29 priorities as an explicit ordered chain)
- **§3 Business Logic & Workflows** (9 subsections) — 3.1 Intake and Exposure Assessment, 3.2 Calendar Seeding/Budgeting/Activation, 3.3 Panel Governance and Engagements, 3.4 Spend Ledger (accruals/posting/reversal), 3.5 Holds and Custodians, 3.6 Vendors and Work Orders, 3.7 Deadline Outcomes and Jurisdictional Freezes, 3.8 Settlement Authority/Negotiation/Payment (with two #### sub-parts), 3.9 Resolution/Reopening/Closure/Portfolio Oversight
- **§4 Endpoint Definitions** — 4-column table, 109 rows
- **§5 Error Code Catalogue** — 2-column table, 29 rows

## Coverage check results

- **Contract 1 (field names): PASS** — 91/91 entity fields, 88/88 endpoint input/output identifiers, 26/26 query params, 29/29 error IDs, 8/8 role names, 44/44 state values, all enum values present in backticks. (One repair during the pass: `WITHDRAWN` was initially only implied; the withdraw sentence now names it.)
- **Contract 2 (rule coverage): PASS** — verified by full-document audit read: all 29 validation priorities with explicit ordering (§2.11); both OCC rules with `expected_matter_version` + `ERR_STALE_MATTER_VERSION`/412 in stale-version framing only; all ~75 state transitions across 12 machines with preconditions and side effects; all 9 calculations with formulas reconstructible from prose (tier classification incl. conservative variant and strict-less-than boundary; reserve ladder incl. post-resolution and reopened variants; accrual rollup; utilization floor with the 89,999/100,000 → 89 example; posture precedence ladder; vendor capacity rollup; per-tier-floored work-order cost; authority routing with rank ladder and single/dual boundary; portfolio analytics); cross-entity cascades (resolution pin-ordered work-orders→holds→custodians→deadlines; firm-suspend engagement cascade; budget supersession; adjustment voiding) and sibling-branch symmetry (two resolve doors contrasted, withdraw×4, expire×3, cancel/terminate/release pairs).
- **Contract 3 (§3 path purity): PASS** — 734 backticked tokens scanned in §3, zero paths/methods.
- Endpoint table: 109/109 paths present, per-row role sets match the scaffold exactly (via "Read set"/"Read set + CFO" shorthands defined in the §4 intro). Error table: 29/29 with exact HTTP statuses.

## Key scaffold-to-prose translation decisions

1. **Unmapped error assignments** (scaffold states the precondition but no validation entry maps it): payment-submit amount ≠ settlement ask → `ERR_FIELD_CONSTRAINT`; settlement execute without a staged `FINANCE_APPROVED` payment → `ERR_REFERENCE_STATE_INVALID`; `NON_MONETARY` amount ≠ 1 cent → `ERR_FIELD_CONSTRAINT`; PATCH outside allowed states → `ERR_INVALID_STATE`; missing `court_order_reference`/`reopen_reason` → `ERR_INVALID_REQUEST`. The accept-counter and withdraw requester-identity gates are stated as rules without pinning an error ID, since the catalog has no fitting entry.
2. **Dual-approval role reconciliation**: the approve precondition ("acting role MUST equal policy `approver_role`") is reconciled with the calc's "second approver strictly higher rank" by framing the policy role as the *first* approver and the higher-ranked role as the second.
3. **Jurisdictional deadline vacate**: the field description ("cannot be vacated by counsel") conflicts with the transition precondition (manual vacate allowed *with* `court_order_reference`); I followed the transition/validation reading and noted the system-cascade bypass.
4. **Zero-Silence spells**: scaffold-implicit behaviors spelled out — successful budget/settlement creates increment the parent matter's `version` (load-bearing for OCC); derived-field recomputes count as mutations (`updated_at`/`version`); `DRAFT` settlement/payment records have no requester yet so draft withdrawal/cancellation is ungated; a `DRAFT` hold cannot be pinned by work orders; the 25,000,000-cent tier boundary landing in `TIER_2`; portfolio cohorts returning zeros rather than nulls.
5. **Precision regime**: this scaffold uses integer cents with floor division throughout (not the example's 2-decimal round-half-up), so §2.5 states that contract explicitly, including per-tier floor-before-sum rounding for work-order costs.

## Step 5: Generate Unit Tests — 2026-08-14T17:04:53.000Z

All audits pass. Generation is complete. Final summary:

## Summary — task_1768_corporate_litigation_matter_management

**Output** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/`):
- `test_helpers/`: `types.py` (15 TypedDicts + 24 enums; AccrualEntry correctly omits `version`/`updated_at` per the append-only rule), `api_client.py` (113 methods, one per PRD endpoint), `api_errors.py` (29 error IDs + HTTP map, registered with the framework), `assertions.py`, `factories.py`, `constants.py` (tier boundaries, reserve bases, 90/100 utilization thresholds, work-order pricing tiers, 5-day cooling), `test_users.py`, `fixtures.py`, `__init__.py`.
- `test_suite/`: `conftest.py` + 9 test files, **79 tests total** (all collect cleanly; pyflakes clean).

**Tests per queue:** Queue A (Difficulty) = **34 tests** (17 instances × 2). Queue B (Corner) = **45 tests** covering all 44 non-stub instances (the tier-boundary instance was split into an at-boundary/one-cent-under pair).

**Per-file counts:** test_01 intake/exposure 10, test_02 RBAC/auth/SoD 8, test_03 budgets/OCC 4, test_04 engagements/firms 9, test_05 accrual ledger 11, test_06 holds/custodians 4, test_07 work orders 14, test_08 settlements/payments 13, test_09 resolution/reporting 7 — wait, file totals: 10+8+4+9+11+4+14+13+7 = 80 lines of count vs 79 collected; exact split verified by collection (79) and the tag audit (34 A + 45 B).

**Design-tag audit:** every test has exactly one `Design:` line; all resolve to real instances with correct rule_id/section; all 8 `excluded_because` stub pointers resolve to real difficulty instances. No scaffold references in generated code.

**Instance skipped (1):** `Difficulty/priority_pair_validation_conflict/engagement_approve_state_vs_fiscal_priority` — its required state (a REJECTED engagement carrying an over-cap rate) is unreachable through PRD endpoints: PRD §3.3 pins create-time rate-cap rejection (itself asserted by the corner instance `error_rate_cap_exceeded_on_engagement_create`), no endpoint mutates `proposed_rate_cents` or the firm cap, so the priority-pair collision cannot be constructed. Gap left as gap.

**PRD-first corrections applied (documented, not weakened):**
- `payment_disburse_rail_gate_and_idempotent_terminal`: the corner YAML pre-computed `ERR_INVALID_STATE` for confirm-receipt from rail NOT_SENT, but PRD §3.8 verbatim pins rail-state violations to `ERR_PAYMENT_RAIL_STATE` — asserted per PRD.
- `accrual_adjustment_reversal_voids_original`: the accrued-to-date value after an adjustment posts is not uniquely derivable (formal POSTED-only rollup yields −500000; the "keeps the ledger balanced" narrative implies 0) — asserted only the unambiguous outcomes (reversed entry VOID, adjustment POSTED).
- `matter_creation_applies_defaults_and_system_fields`: initial `version == 1` is not PRD-pinned ("increments by exactly one on every mutation" sets no origin) — asserted presence/type only; matter_number asserted as the PRD-pinned pattern `MTR-<4-digit year>-<6-digit sequence>`.
- `work_order_authorize_requires_hold_issued`: the recipe creates the work order against a DRAFT hold, but PRD §3.6's creation paragraph pins the hold-state check at create (two-reader conflict) — reconstructed via the uniquely-derivable path (create against ISSUED hold, then release it; DRAFT orders don't pin) hitting the same §2.10 `ERR_CROSS_REFERENCE_MISMATCH` rule at authorize.
- `reserve_recognition_evaluation_order_circular` and all settlement-chain instances: the recipes' exposure triplet (1M/4M/60 → 1.5M expected loss) actually classifies TIER_1, not the TIER_2 their arithmetic assumed — repaired inputs to genuine TIER_2 triplets so the pre-computed literal asserts (1,100,000 / 1,500,000; policy-tier routing) hold as written.

**test_helpers design decisions:** fixtures are plain functions over the module-level `api_client` (single session client) using `get_success_data` for setup; the canonical chain is `make_staff_quartet` → `setup_staffing_matter` → `setup_active_matter` (matter + seeded deadline + OCC-guarded approved budget + approved firm + active engagement + ACTIVE matter), with `fresh_matter_version` re-reading before every version-guarded create; hold/vendor/work-order (`add_hold(issue=/acknowledge=)`, `add_vendor`, `create_and_authorize_work_order`), accrual lifecycle, settlement (`create_tier2_policy`, `create_settlement_under_review`, `setup_settlement_pending_matter`), and payment (`setup_resolved_judgment_matter`, `create_finance_approved_payment`, `setup_disbursed_payment`) tiers on top. Identity mapping: all seven entity-backed roles get `make_<role>_headers(user_id)` builders; ctx dicts carry identity-bound headers per staff user; only the identity-free `LegalOperationsAnalyst` actions and opaque `BoardCommittee` use shared `TEST_USERS` constants.

## Step 6: Generate Implementation — 2026-08-14T17:04:53.000Z

Implementation complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/workspace/implementation/`:
- `start.sh` — guarded pip install (skips when flask importable) + `exec python3 app.py`
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry point, envelope-shaped error handlers, route registration
- `db.py` — in-memory `Store` (dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), UUID/seq/matter-number minting, timestamp formatters, ISO-8601 parser
- `errors.py` — full 29-entry error catalogue with HTTP statuses
- `response.py` — success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — X-User-ID/X-User-Role auth (8 roles), role gating, limit/offset pagination (default 10, clamp 1..100), filters
- `validation.py` — priority-11 field-constraint checks and priority-23 strict shape checks (undeclared/missing/empty/malformed)
- `serializers.py` — per-entity field projection; AccrualEntry serialized with only `id`+`created_at` (append-only ledger row, no `updated_at`/`version`)
- `calc.py` — calculations, derived-field recompute, cascades, clock sweeps
- `routes_a.py` (clock, staff users, counsel firms), `routes_b.py` (matters + lifecycle + summary), `routes_c.py` (engagements, budgets, accruals), `routes_d.py` (holds, custodians, vendors, work orders, deadlines), `routes_e.py` (authority policies, settlements, payments, portfolio report)

## Endpoint count
**109 API endpoints** implemented — every row of the scaffold/PRD endpoint table (verified via Flask route listing: 110 rules including Flask's built-in static route).

## State machines implemented (10)
Matter (INTAKE→ASSESSMENT→STAFFING→ACTIVE→SETTLEMENT_PENDING→RESOLVED→REOPENED/CLOSED cyclic, owner-gated transitions, both resolution doors with the pinned cascade order work-orders→holds→custodians→deadlines), Engagement (PROPOSED branch + ACTIVE↔SUSPENDED cycle, supersede compensation, firm-suspend cascade), Budget (with supersession chain — approval excludes the `prior_version_id` target from the unique-active invariant so supersession is reachable), AccrualEntry (append-only ledger with ADJUSTMENT compensating reversal), LitigationHold (with ISSUED→ACKNOWLEDGED bubble-up from custodian states, never on all-exempted), HoldCustodian (5-day escalation cooling on the logical clock), CounselFirm (panel lifecycle + engagement cascade), VendorWorkOrder (posture/clearance/capacity/half-open temporal gates), Deadline (MET/MISSED/VACATED/EXPIRED, jurisdictional freeze), SettlementRequest (negotiation cycle, dual-approval self-loop with role-rank ordering, snapshot-tier routing, system expiry), PaymentRequest (two independent dimensions: approval lifecycle + NOT_SENT/SENT/CONFIRMED/RETURNED rail with accrual unwind/re-accrue).

## Calculations implemented (8)
exposure_tier_classification (floor-div midpoint, conservative high-end variant for CLASS_ACTION/REGULATORY, strict-less-than boundaries), reserve_recognition (tier base × probability, accrued subtraction floored at zero, post-resolution staged-payments variant, reopened full-restoration variant), matter_accrual_rollup (POSTED entries + DISBURSED payments with SENT/CONFIRMED rail), budget_utilization (floor percent), matter_posture (pinned precedence ladder: jurisdictional miss > RESOLVED/CLOSED > status restriction > budget 100/90 thresholds), vendor_capacity_rollup, work_order_cost (marginal tiers 100/500 GB at 100%/80%/60% with per-tier floor division, final variant on actual_gb>0), settlement_authority_routing (snapshot tier, ≤max single / ≤dual dual-path, second approver strictly higher rank), portfolio_outcome_analytics (per-tier cohorts always emitted, floored means, open-exposure totals).

The logical clock endpoint (`POST /litigation/_clock/set_current_utc`) runs the three sweeps in pinned order (SCHEDULED→MISSED with jurisdictional freeze, MISSED→EXPIRED at +30d, settlement SUBMITTED/UNDER_REVIEW/COUNTERED→EXPIRED with approval reset), using strict `due_at/expires_at < clock` comparisons.

## Boot contract
Verified: `bash start.sh` runs the server in the foreground via `exec`, binds `0.0.0.0` on `$PORT` (default 10000 confirmed), boots in ~2s, store is empty at boot (`total_count: 0` on first list), and repeated fresh-process boots are clean (no disk/SQLite/seed state). Two smoke suites (85-check happy path + ~50-check adversarial pass covering sweeps, dual approval, OCC 412s, SoD, cascades, rail recovery, adjacency, freeze/unfreeze) pass against fresh boots.

## Step 7: Test/Fix Diagnostic Loop — 2026-08-14T17:20:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 79 tests/round).

- **Round 1 sweep**: 78/79 in all 8 rounds; single deterministic failure —
  `test_08_settlements_payments.py::TestPaymentRailAndAccrual::test_settlement_payment_submit_requires_approved_settlement`
  failed with `TypeError: get_success_data() takes 1 positional argument but 2 were given`.
- **Diagnosis**: TEST BUG (test_suite layer). The rule asserted — SETTLEMENT payment submit requires the linked
  settlement `APPROVED`, else `ERR_REFERENCE_STATE_INVALID` — is verbatim PRD §3.8 and uniquely derivable, and the
  implementation already enforces it (`routes_e.py::submit_payment`). The test called the lenient one-argument
  setup helper `get_success_data(resp, 201)` where it meant the strict envelope validator
  `validate_success(resp, 201)`.
- **Fix**: `test_suite/test_08_settlements_payments.py` — swapped `get_success_data` → `validate_success` at the
  payment-create line. No test deletions; no implementation changes.
- **Round 2 sweep (verification)**: 79/79 in all 8 rounds. Clean exit.

Orchestrator-recorded verbatim subagent summary:

Clean 8-round sweep achieved: **79/79 passed in every round** (632/632 total executions).

## Summary

- **Iterations run:** 2 (initial sweep → 1 deterministic failure; fix → verification sweep, all 8 rounds green).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/test_suite/test_08_settlements_payments.py` — `TestPaymentRailAndAccrual::test_settlement_payment_submit_requires_approved_settlement`: the test called `get_success_data(api.create_payment_request(...), 201)`, but `get_success_data()` takes exactly one positional argument (it is the lenient setup helper), so the test died with `TypeError` before reaching its assertion. Swapped to `validate_success(..., 201)`, the strict envelope validator that accepts an expected status. The asserted rule itself — "a `SETTLEMENT` payment requires the linked settlement request to be `APPROVED` (else `ERR_REFERENCE_STATE_INVALID`)" — is verbatim PRD §3.8, uniquely derivable, and the test's setup/request/assertion are PRD-faithful, so only the mechanical helper misuse was corrected. A static AST arity check confirmed no other `get_success_data` misuse anywhere in `test_suite/` or `test_helpers/`.

- **Fixes applied to `implementation/`:** None — the implementation (`workspace/implementation/routes_e.py::submit_payment`) already enforces the rule correctly; all other 78 tests passed in every round of both sweeps.

- **Note on a flakiness false-alarm:** interim stdout from sweep 1 appeared to show `test_settlement_offer_expiry_sweep FAILED`, but that was a mid-line splicing artifact of 8 concurrent pytest streams sharing one output file; the authoritative per-round `results.*.json` showed it passed in all 8 rounds of both sweeps.

## Step 8: Finalize PRD — 2026-08-14T17:31:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/workspace/PRD_FINALIZED.md` written, identical to PRD.md.

## Summary

**Line counts / %-delta:** PRD.md = 389 lines; PRD_FINALIZED.md = 389 lines; delta = 0 lines, 0.0%. `diff` confirms the files are byte-identical.

**Changes:** None.

**Rationale — the entire `<step_7_diff>` resolves to a pure test-mechanics bug with zero PRD silence or mismatch:**

The single Step 7 fix was in `test_suite/test_08_settlements_payments.py` (`TestPaymentRailAndAccrual::test_settlement_payment_submit_requires_approved_settlement`, now at line 269): the test called `get_success_data(api.create_payment_request(...), 201)`, but `get_success_data` is defined at `/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/testing/validators.py:136` as `get_success_data(response)` — exactly one positional parameter — so the call died with `TypeError` before reaching any assertion. The fix swapped to `validate_success(response, expected_status)` (validators.py:27), the arity-correct strict validator. This is a fixture/helper-misuse correction only; it reveals nothing about PRD ambiguity.

**Verification that the asserted rule is already PRD-pinned and impl-conformant:**
- PRD §3.8 (PRD.md line 223) states verbatim: "a `SETTLEMENT` payment requires the linked settlement request to be `APPROVED` (else `ERR_REFERENCE_STATE_INVALID`) and its amount must equal the settlement's `proposed_amount_cents` exactly (else `ERR_FIELD_CONSTRAINT`)" — exactly what the test asserts, so the PRD uniquely determines the behavior.
- Implementation enforces this at `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/workspace/implementation/routes_e.py:486-489`: on payment submit, for `SETTLEMENT` kind, if the linked settlement is missing or not `APPROVED`, it raises `ERR_REFERENCE_STATE_INVALID`. Impl matches PRD; no divergence to pin.

**Per-edit pre-edit search log:** No edits were committed, so no (a)/(b)/(c) entries exist. The investigative greps performed (helper arity in `test_helpers/` and the runner's `testing/validators.py`; the rule text in PRD §3.8; the enforcement site and sibling settlement/payment gates in `routes_e.py:345-355, 486-489, 527`) all corroborated that no PRD wording change is warranted.

## Step 9: PRD Completeness Scan — 2026-08-14T17:45:00.000Z

The file is complete and verified. Here is the summary.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1768_corporate_litigation_matter_management/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 389 lines / 71,108 chars → PRD_COMPLETED.md 391 lines / 76,215 chars (**+2 lines, +5,107 chars**), 22 inline edits, no new sections, no new paragraphs beyond one list-adjacent sentence in §2.2.

**Counts:** 17 ambiguity-pins, 5 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — server never looks `X-User-ID` up in the staff directory; ownership checks are plain equality; "the owning counsel" phrasing names the typical actor, with personal identity gates only where explicitly declared (enumerated) — `middleware.py:28-42` (auth never touches `store.staff_users`)
- §2.1 — revise — **mismatch** — `job_family` is descriptive only; PRD said it "constrains which X-User-Role values that user may legitimately act under" but impl enforces no job-family-to-role mapping — `middleware.py:6-42`
- §2.2 — insert — ambiguity — unknown paths and unsupported methods both yield `ERR_NOT_FOUND` (404); unexpected server failures surface as `ERR_INVALID_REQUEST` (400) — `app.py:18-32`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped (limit→[1,100], offset→≥0); sort is creation order with creation-sequence tie-break (deadline list: due_at then creation sequence); filters are exact-match equality, conjunctive; boolean filters accept case-insensitive true/false, other values ignored; `has_more` = `offset + page_size < total_count` — `middleware.py:53-112`, `response.py:23-34`, `routes_d.py:576`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `db.py:101-108`
- §2.6 — insert — ambiguity — datetime inputs are ISO 8601, offsetless read as UTC, date-only as midnight UTC; clock setter accepts any parseable instant (no monotonicity check); all state-transition stamps come from the logical clock; logical-clock-stamped values and echoed client datetimes render with a 3-digit fraction only when non-zero (`2026-08-01T00:00:00Z`) — `db.py:57-92`, `routes_a.py:44-52`
- §2.6 — insert — ambiguity — `MISSED`→`EXPIRED` sweep has no posture side effect; settlement-expiry sweep also clears the recorded counter amount — `calc.py:306-316`
- §2.11 — revise — **mismatch** — absent/unparseable JSON body treated as empty object; carve-out: checks 24 (engagement activate), 25 (matter activate), 27 (custodian acknowledge), 29 (disburse/confirm-receipt/mark-returned/redisburse) run *before* the step-23 shape check, and PATCH matter runs state check (5) before body-FK existence (4) — `middleware.py:45-50`, `routes_c.py:266-268`, `routes_b.py:226-238`, `routes_d.py:272-274`, `routes_e.py:528-531/547-549/560-562/576-578`, `routes_b.py:147-153`
- §3.1 — revise — ambiguity — `matter_number` four-digit year is read from the logical clock at creation — `db.py:43-45`
- §3.1 — insert — ambiguity — until the exposure triplet is complete, `exposure_tier` and `reserve_amount_cents` remain null — `calc.py:43-59,84-100`
- §3.2 — insert — ambiguity — advancing to STAFFING with no deadline is rejected with `ERR_INVALID_STATE` — `routes_b.py:205-206`
- §3.2 — revise — **mismatch** — budget-approve unique-active invariant excludes the budget named by `prior_version_id` (it is about to be superseded) — `routes_c.py:425-433`
- §3.2 — insert — ambiguity — REOPENED→ACTIVE activation does not re-require an APPROVED budget — `routes_b.py:231-237`
- §3.3 — insert — ambiguity — conflict screening may be recorded at any panel status — `routes_a.py:152-162`
- §3.5 — insert — ambiguity — custodians may be added while the hold is DRAFT, ISSUED, or ACKNOWLEDGED; only RELEASED refuses (`ERR_INVALID_STATE`) — `routes_d.py:218-220`
- §3.5 — revise — ambiguity — issuance refreshes `noticed_at` of NOTICED custodians to the current clock, but a custodian already stamped with that instant is left untouched (no version bump) — `routes_d.py:178-182`
- §3.5 — revise — **mismatch** — releasing a DRAFT hold does not cascade custodians; the custodian cascade applies only on release from ISSUED or ACKNOWLEDGED — `routes_d.py:200-201`, `calc.py:225-238`
- §3.7 — insert — ambiguity — non-jurisdictional vacate: `court_order_reference` optional but non-empty when supplied; the reference is not stored — `routes_d.py:623-627`
- §3.8 — insert — ambiguity — settlement rejection and withdrawal both clear any recorded counter amount — `routes_e.py:334-336,373-375`
- §3.9 — revise — **mismatch** — post-resolution reserve is staged (FINANCE_APPROVED) payments minus the matter's full `accrued_to_date_cents` (posted accruals plus disbursed unreturned payments), not merely "posted accruals" — `calc.py:84-90`
- §3.9 — insert — ambiguity — INTAKE close with any child record fails with `ERR_HOLD_COMPLIANCE_BLOCK`; `close_checklist_ack` missing or false → `ERR_INVALID_REQUEST` — `routes_b.py:310-338`
- §3.9 — revise — ambiguity — portfolio `cohorts` always contains all four tiers in TIER_1→TIER_4 order; `open_exposure_cents` and `total_matters` are computed over the filtered set; null-tier matters belong to no cohort but count toward `total_matters` — `routes_e.py:614-663`

**Verification notes:** impl-only behaviors confirmed against tests as cross-reference (budget supersede chain test exercises the prior-version exclusion; hold tests confirm `2026-08-01T00:00:00Z` millisecond-free rendering). Everything else in impl (tier/reserve/posture ladders, work-order tiered pricing, ledger rollup, sweep ordering and strict-inequality boundaries, OCC semantics, SoD and authority routing, serializer field sets, per-endpoint roles and filters) was already uniquely pinned by the PRD and left untouched.

Note: Steps 8 and 9 touched only PRD documents (PRD_FINALIZED.md, PRD_COMPLETED.md); implementation/ and test artifacts were not modified after the final green 8-round sweep.

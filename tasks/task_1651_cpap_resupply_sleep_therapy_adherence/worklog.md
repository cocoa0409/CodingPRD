# Worklog — task_1651_cpap_resupply_sleep_therapy_adherence

## Step 1: Create Task Directory — 2026-08-14T04:45:00.000Z

Pre-assigned task directory `tasks/task_1651_cpap_resupply_sleep_therapy_adherence/` with `workspace/` subdirectory already created by the pipeline launcher. No index scan or new directory creation performed (per launcher instruction — concurrent pipeline runs in repo).

## Step 2: Generate Scaffold — 2026-08-14T05:17:23.000Z

Clean lint. Final summary of what was generated:

---

## Scaffold artifacts created for task 1651

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_1651_cpap_resupply_sleep_therapy_adherence/`

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7; no `scaffold_difficulty_design` or `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Domain design:** Sleep-DME supplier managing CPAP resupply. Primary archetype = **compliance/audit** (payer-schedule eligibility, adherence documentation, segregation of duties between clinical clearance and fiscal authorization); secondary = **temporal windowing** (cadence windows, 30-day adherence look-back, rental-month anniversaries, 30-day mask-exchange window).

**Structural DNA (§0.3):**
- 9 entities (Patient, PayerPolicy, DeviceEnrollment, ComponentSupplyPlan, ResupplyOrder, AdherenceReport, MaskExchange, RentalContract, RetrievalCase) — flat topology with cross-aggregate FKs and a self-referential `MaskExchange.superseded_by_exchange_id`
- 7 state machines, including **parallel dimensions** on ResupplyOrder (`auth_status` × `fulfillment_status`) and RentalContract (`billing_status` × `equipment_status`), and a **cyclic** Patient status machine (ACTIVE ↔ NON_COMPLIANT_HOLD)
- 52 endpoints (incl. `/_clock/set_current_utc` and `/_ops/run-daily-sweep` test-driving endpoints; clock default `2026-08-01T00:00:00Z`)
- 27 validations, 45 errors, 4 roles (OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist) with **segregation-of-duties** between RespiratoryTherapist (clinical-clear) and BillingSpecialist (authorize)
- 2 OCC concurrency rules on Patient.version (`order-authorize-stale-patient`, `order-ship-stale-patient`)

**Difficulty features (§1.8, 18 instances, all 9 rules × 2):**
- **dual_variant_calc**: adherence provisional (÷nights_reported) vs final (÷compliance_window_days) — 72.0 vs 60.0 on identical inputs; rental straight-line projection vs actual-usage with pause-driven divergence
- **combinatorial_formula**: mask-exchange window+count+anchor three-input intersection (mode a); coinsurance per-line vs per-unit rounding order pinned (mode b, 1-cent divergence)
- **non_linear_state_machine**: ResupplyOrder parallel auth/fulfillment dimensions; Patient cyclic adherence-driven status
- **transitive_cascade**: AdherenceReport.finalize → Patient → RentalContract+ComponentSupplyPlan (depth 3); RetrievalCase.reconcile → Patient → plans+rental (depth 2)
- **priority_pair_validation_conflict**: state-vs-business_temporal on order create (p5 beats p6 beats p8); business_safety-vs-business_constraint on authorize (SoD p13 beats OCC p14)
- **boundary_precision_check**: adherence 70.0 == threshold passes (inclusive >=); cadence `next_eligible_on` day-boundary inclusive
- **cross_entity_state_dependency**: ResupplyOrder→Patient status gate; MaskExchange→DeviceEnrollment window-anchor derivation
- **resource_temporal_overlap**: component half-open cadence window vs mask-exchange rolling aggregate-capacity window (different interval semantics)
- **compensating_invariant**: Patient.outstanding_balance_cents unchanged by RETURNED-before-INVOICED; RentalContract.rental_months_billed unchanged by pause/resume cycle

**Corner design (§1.9):** 33 active instances + 6 `excluded_because` stubs across all 9 sections of the claim-extraction guide (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model).

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
583 calls scanned across both design files; all endpoints, roles, payload fields, captures, and OCC dynamic-version checks pass; every FK has a reverse-reachability GET.

**Key arithmetic pre-computed as literals** (verified by running the formulas): adherence 18/25→72.0 provisional vs 18/30→60.0 final; boundary 21/30→70.0 compliant; coinsurance 33333×3×0.20→20000 (per-line) vs 20001 (per-unit); cadence 2026-08-01+90d→2026-10-30 mask, +30d→2026-08-31 cushion, +14d→2026-08-15 filter; mask-exchange window anchor 2026-08-01+30d→last valid 2026-08-31; rental straight-line 3-month projection from 2026-08-01 → 2026-11-01 vs actual-usage conversion at 2026-12-01 after a 1-month pause.

## Step 3: Copy Shared Files — 2026-08-14T05:17:56.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1651_cpap_resupply_sleep_therapy_adherence/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T05:25:31.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1651_cpap_resupply_sleep_therapy_adherence/workspace/PRD.md` (299 lines). The two prohibited design files were never opened.

**Document structure** (domain-derived, per the skill's diversity rules):
- §1 Introduction — 2 paragraphs from a business-context angle
- §2 Global Specifications — 10 subsections: RBAC with opaque-identity prose for all four roles, verbatim §2.2 response envelope, pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending), resource identity/timestamps/versioning, logical clock (startup 2026-08-01T00:00:00Z) + daily sweep, OCC on `expected_patient_version`, fixed request-evaluation order (with `ERR_INVALID_REQUEST` explicitly lowest priority), money/rounding/inclusive-boundary rules, segregation of duties, parallel state dimensions
- §3 Business Logic — 8 subsections by lifecycle: payer policies → intake/enrollment → setup cascade → adherence dual-variant reporting → resupply pipeline → mask exchanges → rental billing/conversion → discontinuation/retrieval
- §4 endpoint table (4 columns, 52 endpoints), §5 error catalogue (2 columns, 45 errors)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 74 required, 74 present, 0 missing
- endpoints[].request_body: 33 required, 33 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed (global order in §2.7; per-endpoint orders in §3.5/3.6/3.7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (authorize + ship; expected_patient_version + ERR_STALE_PATIENT_VERSION/412 named; no simultaneity framing), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (dual-variant adherence, compliance determination, cadence gate, exchange window/count, dual-variant rental accrual, coinsurance per-line rounding, balance aggregation, reminder sweep formula added after first-pass gap), 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed, 0 missing
- entities[].fields[] structured content: 74 checked, 74 reconstructible (defaults, nullability, initial states, computed derivations), 0 missing
- sibling-branch symmetry: 8 groups checked (deny/authorize, invoice/return, finalize/reject, deny/cancel exchange, 3 close-unrecoverable sources, 2 cancellation sources, dual adherence variants, dual rental variants), 8 symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 377
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes:** (1) First-pass mechanical check had a false-positive caused by the fenced JSON blocks in verbatim §2.2 skewing backtick pairing; re-ran with fences stripped — all clean. (2) One genuine gap was caught and fixed during Contract 2 review: the reminder-outreach sweep calculation (`REMINDER_LOOKAHEAD_DAYS: 7`, skip-first-fill, re-remind only after new dispense) was initially only summarized in §2.5; a full-formula prose paragraph was added to §3.5. (3) All 16 enum value sets, all 45 error IDs (backticked in §2/§3 prose), and all 4 role names verified present verbatim.

## Step 5: Generate Unit Tests — 2026-08-14T05:55:13.000Z

All 70 tests collect cleanly. Generation complete.

## Summary

**Generated for task_1651 (CPAP Resupply & Sleep Therapy Adherence):**

**Stage 1 — `test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1651_cpap_resupply_sleep_therapy_adherence/test_helpers/`):
- `types.py` — 14 status enums, role enum, 9 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 56 methods covering all 52 PRD endpoints under `/sleep-therapy`
- `api_errors.py` — 45 `ApiErrorId` values with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions
- `factories.py` — payload factories (unique `plan_code`/`device_serial` minting per call)
- `constants.py` — PRD thresholds (70% / 4.0h / 30-day window, cadences 90/30/14/90, 30-day exchange window, 7-day reminder lookahead, 14-day retrieval deadline)
- `test_users.py` — 4 opaque-role header constants (`rt-1`, `bs-1`, …) + `make_*_headers` builders (needed for segregation-of-duties tests where authorizer X-User-ID must equal the clearing clinician's)
- `fixtures.py` — composite helpers: `setup_therapy_patient` (clock→policy→patient→enroll→begin/complete-setup→plans→rental), order lifecycle (`create_order_for_plan` auto-reads plan `quantity_per_cycle` and fresh patient version, `create_cleared/authorized/shipped_order`, `dispense_component`), adherence (`ingest_and_finalize_report`, `finalize_(non)compliant_report`), mask exchanges, discontinuation/retrieval flows, `expected_coinsurance_share` (Decimal ROUND_HALF_UP on line total × 0.20)
- `__init__.py` — barrel export

**Stage 2 — `test_suite/`**: `conftest.py` + 9 domain-named files, **70 tests total**.

**Audit results (all green):**
- All 18 difficulty instances (§1.8) have exactly ≥2 tests each (36 tests)
- All 33 non-stub corner instances (§1.9) have ≥1 test each (34 tests); all 6 `excluded_because` stubs were verified to resolve to real difficulty instances and emitted no tests
- Every test ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 70 tags resolve against the source YAMLs
- Every docstring PRD citation verified to literally grep-match `PRD.md` (0 failures)
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code

**Notable PRD-first adjudications:**
- `resupply_order_invalid_transition_ship_before_authorize`: the literal recipe (ship from `PENDING_CLINICAL_CLEARANCE`) fails unique-derivability — both `ERR_ORDER_NOT_AUTHORIZED` and `ERR_ORDER_NOT_READY_TO_SHIP` are simultaneously violated and PRD §3.5 does not order those two checks. Per the validation-priority silence pattern, the test isolates the single failure instead: authorize → ship once (auth stays `AUTHORIZED`, fulfillment leaves `READY_TO_SHIP`) → ship again with fresh OCC version → `ERR_ORDER_NOT_READY_TO_SHIP` is the only firable error.
- `rental_bill_before_period_due_rejected`: kept as-is — PRD §3.7 explicitly fixes the check order ("the monthly anniversary must have arrived … (`ERR_RENTAL_PERIOD_NOT_DUE`); the contract must be in `BILLING` status …"), so the asserted error is uniquely derivable even though the contract is also still `SCHEDULED`.
- `sod_vs_stale_version_on_authorize`: the source recipe's version never actually goes stale (clinical-clear doesn't mutate Patient), so both emitted tests genuinely advance `Patient.version` (via a compliant finalization in one, via a second order's authorize in the other) before asserting `ERR_SEGREGATION_OF_DUTIES` fires ahead of the OCC failure.
- `quantity_mismatch_rejected`: quantity derived live from the plan's `quantity_per_cycle` (+4) rather than hard-coded, since PRD pins only "at least one unit" for auto-seeded plans.

## Step 6: Generate Implementation — 2026-08-14T05:55:13.000Z

Done. The complete implementation is in `/home/ubuntu/github/CodingPRD/tasks/task_1651_cpap_resupply_sleep_therapy_adherence/workspace/implementation/` and boots cleanly per `start.sh` invocation.

**Files produced**
- `start.sh` — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `app.py`, `db.py` (9 empty dicts, no seeding), `errors.py` (full catalog with exact IDs/HTTP codes), `response.py` (envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields in meta for lists only), `middleware.py` (`X-User-ID`/`X-User-Role`, 4 roles, opaque ids), `validate.py`, `util.py` (logical clock defaulting to 2026-08-01T00:00:00Z, calendar-month math, Decimal half-up rounding), `services/core.py` + `services/sweep.py`, and 10 route modules covering all 53 endpoints

**Key semantics implemented per PRD**
- Logical clock drives every business date and entity `created_at`/`updated_at` (3-fractional-digit ISO); a monotonic seq gives deterministic "most recently created" ordering under clock ties
- Validation order per PRD §2.7: auth → role → path 404 → body FK 404 (`ERR_FK_NOT_FOUND`) → state/business → `ERR_INVALID_REQUEST` last
- Resupply pipeline: fixed creation check order (patient → plan → quantity → cadence → prior-auth); clinical-clear with first-fill grace; authorize = state → segregation-of-duties → OCC (412); ship = OCC before readiness checks; authorize/deny/ship each bump `Patient.version` exactly once
- Dual adherence percentages (provisional ÷ nights_reported, final ÷ window; 25/21/30 → 84.0 vs 70.0), inclusive 70% threshold, finalize cascades (hold/resume, plan suspend/resume, rental pause/resume)
- Mask exchanges: anchor selector (setup date / inherit open window / roll forward to prior `completed_on`), window check inclusive (`anchor + window_days`), strict `<` count check, completion resets mask clock and supersedes the latest un-superseded prior
- Rental: sweep activation SCHEDULED→BILLING at 1-month anniversary, bill order = period-due → not-billing → already-converted (PRD §3.7 order), auto-conversion at `rental_months_to_own`
- Discontinuation/retrieval: synchronous DISCONTINUING→DISCONTINUED cascade on reconcile/close-unrecoverable, strict `today > due_on` for unrecoverable, RETRIEVED vs DECOMMISSIONED, return-to-payer chain
- Daily sweep returns `{reminders_sent, rental_activations, patient_discontinuations}` with 7-day reminder lookahead

**Gap resolutions** (spec had no source): `unit_allowable_cents` snapshots a deterministic per-component fee constant (optional body override accepted); `monthly_rental_cents` defaults to 0 (optional complete-setup body override); `compliance_min_nights` stored from input, derived as `ceil(threshold×window/100)` when absent.

**Verification**: a 123-assertion smoke suite covering all five flows (order pipeline/OCC/SoD, adherence hold/resume, exchange windows/roll-forward/supersession, rental conversion, retrieval/reconcile/close-unrecoverable, PURCHASE vs RENTAL, prior-auth, error codes) passes from a fresh boot, and a kill/reboot check confirmed zero carry-over state and clock reset to the 2026-08-01 default.

## Step 7: Run Tests and Iterate — 2026-08-14T05:59:53.000Z

All 8 parallel rounds passed cleanly on the first iteration — the exit condition is met.

**Summary**

- **Iterations run**: 1 (single 8-round parallel stability sweep, all rounds run to completion)
- **Sweep results**: All 8 rounds `passed=70, failed=0, skipped=0, errors=0, total=70`. Per-test outcome distribution verified across every `results.{1..8}.json` — 70 unique tests, every one `passed` in every round. No flakiness signal (no test passed in some rounds and failed in others).
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `implementation/`**: none

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1651_cpap_resupply_sleep_therapy_adherence/workspace/implementation/` was already complete and correct when this diagnostic loop started (per the worklog, it had been generated and smoke-verified in a prior step). The 8-round concurrent sweep under `--isolation per-test-server` confirmed stability with zero intervention required.

Orchestrator verification: independently read all 8 `results.{1..8}.json` files — each reports `passed=70, failed=0, total=70`.

## Step 8: Finalize PRD — 2026-08-14T05:59:53.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T06:13:21.000Z

All edits verified. Here is the final report.

## Summary

**Source vs output:** `PRD.md` (299 lines / 45,128 chars) → `PRD_COMPLETED.md` (299 lines / 48,764 chars). Char delta: **+3,636**. 21 diff hunks, all in-paragraph inserts/revisions; no new sections, no line-count change. (No `PRD_FINALIZED.md` existed; source was `PRD.md`.)

**Counts:** 24 ambiguity-pins, 4 mismatch-revisions.

**Changes** (each maps to one hunk; the §3.3 edit spanned two paragraphs):

- §2.1 — insert — ambiguity — whitespace-trimmed headers; only empty result is "malformed"; an unrecognized non-empty role fails with `ERR_FORBIDDEN_FOR_ROLE` (403), not 400 — implementation/middleware.py:30-52
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the real wall clock, not the logical clock — implementation/response.py:7-11, util.py:25-27
- §2.3 — insert — ambiguity — invalid/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by creation sequence — implementation/routes/helpers.py:28-62
- §2.4 — insert — ambiguity — entity `created_at`/`updated_at` are stamped from the logical clock — implementation/services/core.py:19, util.py:78-80
- §2.5 — insert — ambiguity — clock-set accepts any parseable ISO 8601 datetime, naive values read as UTC, no future-only/monotonicity constraint — implementation/routes/clock.py:13-19, util.py:38-45,70-72
- §2.6 — revise — mismatch — replaced "endpoints other than order authorization and order shipment do not accept a version field": order creation also accepts an optional `expected_patient_version`, stored but never evaluated — implementation/routes/resupply_orders.py:120-127
- §2.8 — revise — mismatch — "one strict comparison" → two strict comparisons (exchange count + retrieval overdue `strictly later than due_on`); also inserted calendar-month clamping rule (Jan 31 + 1 month → Feb 28/29) — implementation/routes/retrieval_cases.py:107, mask_exchanges.py:112, util.py:99-105
- §3.1 — insert — ambiguity — duplicate `plan_code` → `ERR_INVALID_REQUEST` (400); numeric bounds (day-counts ≥ 0; `compliance_window_days`/`max_exchanges_per_window`/`rental_months_to_own` ≥ 1; `compliance_min_hours_per_night` > 0) — implementation/routes/payer_policies.py:23-45
- §3.1 — revise — ambiguity — `compliance_min_nights` may be client-supplied (integer 0..`compliance_window_days`); server derives via ceiling(threshold×window/100) only when omitted — implementation/routes/payer_policies.py:29-33
- §3.2 — insert — ambiguity — NPI accepted only as a string of exactly ten digits (`ERR_INVALID_REQUEST` otherwise) — implementation/routes/patients.py:47-49
- §3.2 — insert — ambiguity — duplicate `device_serial` → `ERR_INVALID_REQUEST` (400); enrollment list filters are `patient_id` and `enrollment_status` — implementation/routes/device_enrollments.py:51-53,67-73
- §3.3 — insert — ambiguity — `quantity_per_cycle` seeded at exactly 1 for all four plans; `monthly_rental_cents` comes from an optional integer (≥ 0) on complete-setup, default 0 — implementation/routes/device_enrollments.py:111-112,127-146
- §3.4 — insert — ambiguity — client may supply `window_start_on`; mismatch vs server-computed start → `ERR_INVALID_WINDOW`; omitted → server computes; `nights_reported`/`compliant_nights` non-negative integers with `compliant_nights ≤ nights_reported` (`ERR_INVALID_REQUEST`) — implementation/routes/adherence_reports.py:39-62
- §3.4 — insert — ambiguity — rejection does not record `reviewed_by_user_id` — implementation/routes/adherence_reports.py:152-161
- §3.5 — revise — mismatch — creation's `expected_patient_version` is optional and unevaluated (PRD implied it was a required creation input) — implementation/routes/resupply_orders.py:120-127
- §3.5 — insert — ambiguity — prior-auth reference satisfied by a non-empty string under any of `prior_auth_reference`, `prior_authorization_reference`, `prior_auth_ref`, `prior_auth` — implementation/routes/resupply_orders.py:48-53,110-118
- §3.5 — revise — mismatch — "the payer's fee schedule" (policies carry no fee fields) → fixed per-component schedule MASK 12500 / CUSHION 4500 / FILTER 900 / TUBING 2200 cents, overridable by `unit_allowable_cents` (int ≥ 0) in the authorize body; also pinned deny-from-other-state → `ERR_ORDER_NOT_PENDING_AUTH` and `denial_reason_code` as required non-empty string — implementation/services/core.py:87-92, routes/resupply_orders.py:197-227
- §3.6 — insert — ambiguity — anchor selector counts prior exchanges of any status (incl. denied/cancelled), ties broken by creation order; expired-window roll uses prior `completed_on`, which may be null, and a null anchor can never pass approval — implementation/services/core.py:174-193, routes/mask_exchanges.py:106-109
- §3.6 — insert — ambiguity — deny from non-`REQUESTED` and cancel from non-`REQUESTED`/`APPROVED` both fail with `ERR_EXCHANGE_NOT_REQUESTED` — implementation/routes/mask_exchanges.py:172-192
- §3.8 — insert — ambiguity — discontinuation suspends every plan not already `CLOSED`; "active rental contract" pinned as `billing_status` ∈ {`SCHEDULED`, `BILLING`, `PAUSED_NON_COMPLIANCE`} — implementation/routes/patients.py:103-116

**Notable non-changes (verified already pinned by PRD):** check ordering on order create/authorize/ship/cancel, cadence/reminder math, two-variant adherence rounding and compliance boundary, invoice coinsurance (20% half-up on line total, balance aggregation over INVOICED orders), compliance-hold and discontinuation cascades, retrieval chain and overdue strictness, sweep summary shape, 201-vs-200 rules, and all list-filter sets except device enrollments.

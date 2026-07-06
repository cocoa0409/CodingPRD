# Worklog — task_0523_lasik_refractive

## Step 1: Create task directory — 2026-07-01T00:00:00.000Z

Created `tasks/task_0523_lasik_refractive/` and `tasks/task_0523_lasik_refractive/workspace/` (pre-specified folder; ID scan skipped per instructions). Verified `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-07-01T00:00:00.000Z

All stub references resolve. The scaffold is complete and passes the lint cleanly.

Generated three scaffold artifacts for **task_0523_lasik_refractive** at **Expert** difficulty, all passing `scaffold_lint.py` (VERDICT: clean lint).

**Design profile:** workflow_orchestration + temporal_windowing archetype; flat entity topology; parallel state-machine shape; peer_roles RBAC; immediate consistency. Complexity layers: dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities**: TreatmentPackage, LaserSuite, Surgeon, Optometrist, Patient, CandidacyScreening, SurgeryCase, FinancingPlan, ConsentForm, EnhancementRequest, SuiteBooking, RefundClaim
- **4 state machines**: CandidacyScreening (branching fork-join APPROVE/REJECT), SurgeryCase (parallel clinical×financial axes), EnhancementRequest (cyclic RE_SCREENING↔REQUESTED), RefundClaim
- **2 concurrency rules**: OCC on SurgeryCase.version for booking-create and cancel
- **5 calculations**: ablation_depth_estimate, residual_bed (ordered dependency), amortized_installment (compound interest), refund_payout (dual-variant PRO_RATA/DEPOSIT_FORFEIT), enhancement_window_eval (datetime boundary)
- **25 validations** (priority-ordered: auth → existence → state → OCC → business safety → referential → temporal → constraint → fiscal)
- **48 endpoints** (includes a `/_clock/set_current_utc` test-driving endpoint with startup default 2026-05-01T00:00:00Z, plus filtered-list/single-resource GETs added to satisfy FK reverse-reachability)
- **25 error codes**; **5 roles** (Coordinator opaque, Surgeon/Optometrist/Patient entity-backed, Anonymous)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 instances = **18 instances**, all grounded, with pre-computed literal assertions (refund 450000 vs 425000; installment 35540; ablation 36 / residual 404; boundary residual exactly 350; enhancement deadline 2027-06-01T12:00:00Z).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 7 sections, **36 instances** (33 active with full test recipes + 3 `excluded_because:` stubs referencing §1.8 instances) — covers entity creation/defaults/computed/system fields, not-found, type constraints, invalid transitions, terminal lockdown, all remaining error codes, RBAC denials, OCC stale-version (412), pagination envelope, and FK reverse-reachability.

All 54 instance names are unique across both design files; 521 setup/trigger calls lint-clean against §1.5.

## Step 3: Copy shared files — 2026-07-01T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0523_lasik_refractive/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-01T00:00:00.000Z

All checks pass. The PRD is complete at `workspace/PRD.md`.

Generated the PRD for the **lasik-refractive-center** domain (API mounted under `/refractive`).

**Document shape**
- 269 lines total.
- **§1** Introduction — 2 paragraphs (system goals + cross-cutting complexity angle).
- **§2** Global Specifications — **9 subsections**: 2.1 RBAC (all 5 roles + every `identity:` translated), 2.2 Response Structure (fixed block emitted verbatim), 2.3 Pagination, 2.4 Common Resource Properties (calls out `TreatmentPackage` as the `common_fields: false` exception carrying only `id`/`created_at`), 2.5 OCC, 2.6 Monetary precision/rounding, 2.7 Logical clock, 2.8 Cascading consistency, 2.9 Nested retrieval + left-to-right validation precedence.
- **§3** Business Logic — **9 subsections** by lifecycle: configuration, patient/screening, case opening + dual axes, financing/installments, scheduling, consent/day-of-surgery, cancellation cascade, enhancement loop, refund guarantee.
- **§4** endpoint table (49 rows) and **§5** error table (25 rows).

**Rule / calculation / error distribution**
- All **5 calculations** rendered as precise prose: ablation depth (§3.2, sum-then-round-half-up), residual bed (§3.2, pinned order after ablation), amortized installment (§3.4, ceil), refund payout dual-variant PRO_RATA vs DEPOSIT_FORFEIT (§3.9, floored at 0), enhancement window (§3.8, strict `<` boundary). Constants embedded (110 µm flap, 12.0 µm/diopter, 1.0 mm zone, 25000-cent fee, 36500-day LIFETIME window, apr÷10000÷12).
- **State machines**: all four (CandidacyScreening, SurgeryCase parallel clinical/financial axes, EnhancementRequest cyclic loop, RefundClaim) with from/to pairs, preconditions paired to error IDs, and every side-effect/cascade stated (3-hop cancel cascade in §3.7).
- **Validations**: four safety gates with explicit priority ordering (residual → K → error → age); both OCC rules with `expected_case_version` + `ERR_STALE_CASE_VERSION` (412).
- **All 25 error IDs** appear in prose; §5 table lists them with HTTP status only.

**Hard contracts (all PASS):** Field-Name Coverage (57/57), Rule Coverage (all), §3 Path Purity (0 violations). Withheld files not opened.

## Step 5 & 6: launched concurrently — 2026-07-01T00:00:00.000Z

(See entries below once each subagent returns.)

## Step 5: Generate unit tests — 2026-07-01T00:00:00.000Z

Test infrastructure complete for `task_0523_lasik_refractive`.

**Stage 1 — `test_helpers/`** (8 files + barrel): `types.py` (TreatmentPackage modeled as `common_fields:false` — id+created_at only), `api_client.py` (one method per endpoint), `api_errors.py` (24 errors), `assertions.py`, `factories.py`, `constants.py` (only PRD-verbatim constants — clinical thresholds omitted), `test_users.py` (opaque Coordinator/Anonymous + per-instance `make_<role>_headers` builders for the three entity-backed roles), `fixtures.py` (composite setups config → scheduled → consented → operated → healed → enhancement/refund-ready, with identity threading).

**Stage 2 — `test_suite/`**: `conftest.py` + 5 domain test files, **58 tests total**.
- **Queue A (Difficulty): 30 tests** covering all 15 kept instances (≥2 each).
- **Queue B (Corner): 28 tests** covering 28 non-stub instances (≥1 each).

Every test carries one verbatim `Design:` tag; all cited PRD sentences pass a literal grep; no skip/xfail; no scaffold leakage.

**Instances skipped (fail unique-derivability — PRD names the constant only abstractly, never states its value):**
- Difficulty `priority_pair_validation_conflict/booking_referential_beats_temporal` & `/consent_referential_beats_constraint` — §2.9 pins ordering only through state/OCC, not among 422-level rules.
- Difficulty `boundary_precision_check/residual_bed_at_exact_minimum_approves` — depends on MIN_RESIDUAL_BED_UM (=350), not in PRD.
- Corner `validations/reject_screening_thin_bed_boundary_349`, `/approve_high_k_rejected_ectasia`, `/approve_high_error_untreatable`, `/approve_underage_rejected`, `state_machines/heal_too_early_rejected` — each asserts an outcome pinned to an unstated threshold.
- Corner `state_machines/reject_screening_sets_reason_and_patient_ineligible` — kept **partially**: `Patient.status==INELIGIBLE` asserted; paired `rejection_reason==THIN_BED` dropped (needs unstated MIN_RESIDUAL_BED_UM).

**Stubs (queue B `calculations`):** 3 `excluded_because` stubs correctly not translated; cross-refs resolve to real §1.8 instances.

## Step 6: Generate implementation — 2026-07-01T00:00:00.000Z

The implementation is complete and verified.

Generated a complete Python + Flask implementation at `workspace/implementation/`.

### Files (20)
- `start.sh` — foreground launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec`s the server.
- `app.py` — Flask app factory, blueprint registration, error handlers, `/health`.
- `db.py` — in-memory `Store` (plain dicts, fresh on every boot, no seeding), UUID/ISO-datetime helpers, logical clock (default `2026-05-01T00:00:00Z`), pinned business constants.
- `response.py`, `errors.py`, `middleware.py`, `helpers.py` — envelope helpers, error catalog, auth/RBAC, validation + pagination utilities.
- `services/calc.py` — the four calculations.
- `routes/` — config, patients, screenings, cases, financing, lookups, enhancements, refunds, clock.

### Endpoints: all 48 from the PRD/scaffold implemented, plus `/health`.

### Key design handling
- **Response envelope** verbatim: `meta` (`api_request_id` prefixed `req_`, `api_request_timestamp` ISO-8601 UTC 3 fractional digits), `response_type` object/array/error, `data`. Pagination fields in `meta` for lists (default 10, min 1, max 100).
- **Auth/RBAC**: `X-User-ID` + `X-User-Role` (401 missing → 403 forbidden); patient registration open to Anonymous. Ownership enforced.
- **Common fields**: tracked entities get `created_at`/`updated_at`/`version`; `TreatmentPackage` carries only `id`+`created_at`.
- **Parallel state machine**: SurgeryCase clinical & financial axes independent; `touch()` bumps `updated_at`+`version`.
- **Cascade** (cancel): releases ACTIVE bookings, revokes SIGNED consents, cancels OPEN financing, flips financial axis to REFUNDED only if PAID_IN_FULL, each child independently version-bumped; then case version++.
- **OCC**: `expected_case_version` → `ERR_STALE_CASE_VERSION` (412), checked after existence, after state gate (state precedes OCC).
- **Calculations**: ablation depth (Decimal, sum-then-round-half-up), residual bed (ablation-first), amortized installment (ceil), dual-variant refund (PRO_RATA vs DEPOSIT_FORFEIT, floored 0), enhancement window (strict `<`). Constants: `MIN_RESIDUAL_BED_UM=350`, `MAX_SAFE_K_DIOPTERS=48.0`, `MAX_TREATABLE_DIOPTERS=8.0`, `HEAL_SETTLE_DAYS=30`, `FLAP_THICKNESS_UM=110`, `GUARANTEE_FEE_CENTS=25000`, `MIN_AGE_YEARS=18`.
- **Validation precedence**: auth → forbidden → existence (404, left-to-right) → body (400) → state (409) → OCC (412) → ordered business rules. Safety gates in pinned order THIN_BED→HIGH_K→HIGH_ERROR→UNDERAGE.

### Verification
Booted cleanly, passed 3 end-to-end smoke suites covering full lifecycle + calculation literals (ablation 36 / residual 404 / boundary 350 & 349, installment 35540, PRO_RATA 450000, DEPOSIT_FORFEIT 425000), RBAC 401/403, safety-gate boundaries, enhancement window exact-boundary, OCC, cascade, validation precedence.
**Note:** constants (esp. `MIN_AGE_YEARS=18`) were inferred from the sibling `SCAFFOLD_*_DESIGN.yaml` docs since main `SCAFFOLD.yaml` referenced them symbolically.

## Step 7: Test-and-fix loop — 2026-07-01T00:00:00.000Z

Two consecutive fully clean 8-round parallel sweeps (16 rounds total, 58/58 each). Exiting with the summary.

**Iterations run:** 3 fix iterations, then 2 confirming clean sweeps (16 rounds total green). Started at 29/58 stable failures (deterministic, 8/8 each — one dominant root cause plus two secondary ones), ended at 58/58 across all 8 parallel rounds, twice.

**Tests deleted:** None. All failures traced to fixture bugs, one mis-translated assertion, and infrastructure flakiness — every assertion was PRD-covered and uniquely derivable.

**Fixes applied to `test_helpers/` (fixtures.py):**
- `setup_scheduled_case` — re-read the case via `get_case` after funding before supplying `expected_case_version` to `create_booking`. The stale pre-funding `case["version"]` was used, but PRD §2.4 says a financial-status change (funding) increments the case `version`, so every downstream booking hit `ERR_STALE_CASE_VERSION`. This was the root cause of ~25 of the 29 failures (all `setup_scheduled_case`/`setup_consented_case`/`setup_operated_case`/`setup_healed_*` chains).
- `setup_blocker_booking` — same fix: re-read version after `fund_case_in_full` before booking the blocker.

**Fixes applied to `test_suite/`:**
- `test_04_scheduling.py` — 8 inline booking sites re-fetch the case after funding so `expected_case_version` is current. The two OCC tests rewrote to observe the stale version *before* funding, then let funding bump the version while keeping the case PLANNED+funded. Isolates the OCC failure: prior version made the case also leave PLANNED, so impl returned `ERR_INVALID_STATE` — and PRD (line 110: "OCC is checked as part of that state layer") does not uniquely order state-vs-OCC when both fail.
- `test_05_lifecycle_and_cascades.py` — `test_cancel_cascade_releases_and_refunds`: assertion changed from `plan["status"] == "CANCELLED"` to `== "SETTLED"`. PRD §3.7 sets *only an open* financing plan to CANCELLED; this test uses `pay_in_full=True` (a SETTLED plan), so the plan stays SETTLED while the case's financial axis flips to REFUNDED (STEP 1c partial-coverage).

**Fixes applied to `implementation/` (app.py):**
- Added an `after_request` hook setting `Connection: close` to disable Werkzeug dev-server HTTP keep-alive. Under 8× concurrent per-test-server reboots the dev server intermittently closed an idle keep-alive socket as the `requests` client reused it, surfacing as transient `BadStatusLine`/`ConnectionError`. Transport-only hardening — no PRD-observable endpoint/field/status change.

## Step 8: Finalize PRD — 2026-07-01T00:00:00.000Z

Done. One edit, one line changed (same total line count).

## Summary

**Line counts:** PRD.md = 268 lines; PRD_FINALIZED.md = 268 lines. One line revised (§3.4), no lines added/removed. Delta ≈ 0.4% of lines touched.

**Changes (one bullet per change):**
- §3.4 — revise — appended a sentence pinning that changing the case's financial status is a mutation that increments the case's `version` by one, so a fresh implementer bumps `version` on funding (and on any financial-status change) just as §3.5/§3.7 explicitly do for scheduling and cancellation — impl `routes/cases.py:114`, `routes/cases.py:131` (funding), consistent with `routes/financing.py:34-35` (installment settlement) and `routes/refunds.py:103` (refund pay).

**Per-edit pre-edit search log:**
- Edit 1 (§3.4 case-version-on-financial-status-change):
  - (a) Subject: the case `version` increment triggered by a financial-axis mutation (funding, installment settlement, refund).
  - (b) Impl paths enumerated/read: `create_financing` outright branch (`routes/cases.py:113-114`, `touch(case)` after setting PAID_IN_FULL); `create_financing` open branch (`routes/cases.py:130-131`, `touch(case)` after DEPOSIT_PAID); `post_installment` (`routes/financing.py:27-35`, `touch(case)` only on the settling installment that flips financial_status→PAID_IN_FULL; non-settling installments never touch the case); refund pay (`routes/refunds.py:100-103`, `touch(case)` after REFUNDED); plus all clinical-axis `touch(case)` sites (booking 248, consent 290, operate 328, heal 354, cancel 394) and the `touch`/`stamp_create` semantics in `helpers.py:10-25` (version starts at 1, `+=1` per touch).
  - (c) Adjustment: worded the guarantee as "whenever the case's financial status changes, the case's `version` increments" rather than "funding/each installment increments." This keeps it true for funding, installment settlement, and refund pay, while remaining silent (correctly) for non-settling installments that do not change financial status and not overreaching onto the clinical-axis transitions.

**Items that produced no PRD edit:**
- §3.7 cancel cascade (test assertion `CANCELLED`→`SETTLED`): PRD §3.7 line 169 already states verbatim that only an *open* plan is set to CANCELLED, a SETTLED plan is untouched, and the financial axis flips to REFUNDED only if it was PAID_IN_FULL. Impl `routes/cases.py:386-392` matches exactly. The Step 7 change was a mis-translated test assertion (fixture using `pay_in_full=True` → a SETTLED plan), not a PRD silence/mismatch. No edit.
- `after_request`/`Connection: close` (app.py): transport-only hardening with no PRD-observable endpoint/field/status behavior. No edit (as instructed).
- fixtures.py version-reread fixes: all downstream consequences of the §2.4/§3.4 funding-version semantics now pinned by Edit 1; no separate PRD edit.

## Step 9: Complete PRD — 2026-07-01T00:00:00.000Z

All 15 edits applied cleanly, line count unchanged (all in-paragraph), char delta +1935. Let me do a final review of a couple behaviors I want to confirm I classified correctly, particularly whether the impl's booking OCC-before-funded ordering or the refund plan selection deserve pins. I've decided both are adequately covered by existing PRD prose (§2.9 precedence, §3.9 singular plan). 

Let me verify the enhancement DENY doesn't require APPROVED re-screening (impl: DENY just sets DENIED regardless) — confirmed in impl, and my edit only qualifies the APPROVE branch. Good.

The task is complete.

## Summary

**Source vs completed:** `PRD_FINALIZED.md` = 268 lines / 36,839 chars; `PRD_COMPLETED.md` = 268 lines / 38,774 chars. Char delta **+1,935**. All changes are in-paragraph inserts/revisions; no new lines, sections, or paragraphs.

**Counts:** 15 changes total — **13 ambiguity-pins**, **2 mismatch-revisions** (see note). No pure mismatches were found (impl never contradicts an already-pinned PRD value); the two "revise" items sharpen prose that admitted an alternate reading.

**Per-change:**
- §2.2 Response Structure — insert — ambiguity — `api_request_timestamp` derived from logical clock, not wall-clock — response.py:15-16
- §2.3 Pagination — insert — ambiguity — limit/offset out-of-range clamping (limit→1..100, offset→0) and non-integer → ERR_INVALID_REQUEST — helpers.py:132-158
- §2.3 Pagination — insert — ambiguity — list tiebreak by `id` ascending when `created_at` ties — helpers.py:164
- §2.4 Common Resource Properties — insert — ambiguity — `version` initial value is 1 — helpers.py:15
- §3.2 Registration — insert — ambiguity — supplied `co_managing_optometrist_id` must resolve → ERR_NOT_FOUND — patients.py:22-25
- §3.2 Submit screening — revise — ambiguity — order pinned: DRAFT state (ERR_INVALID_STATE 409) checked before optometrist-ownership (ERR_FORBIDDEN 403) — screenings.py:87-91
- §3.2 Adjudicate gate 1 — insert — ambiguity — minimum safe residual bed = 350 microns — db.py:9
- §3.2 Adjudicate gate 2 — insert — ambiguity — maximum safe keratometry = 48.0 diopters — db.py:10
- §3.2 Adjudicate gate 3 — insert — ambiguity — maximum treatable diopters = 8.0 — db.py:11
- §3.2 Adjudicate gate 4 — insert — ambiguity — minimum age = 18 years — db.py:12
- §3.2 Reject decision — insert — ambiguity — `rejection_reason` left null when no gate would fail — screenings.py:153
- §3.4 Financing create — insert — ambiguity — non-UNFUNDED financial status → ERR_INVALID_STATE (409) — cases.py:89-90
- §3.4 Outright funding — insert — ambiguity — SETTLED outright plan sets `monthly_installment_cents` = 0 — cases.py:107
- §3.4 Installment — insert — ambiguity — `amount_cents` ≥ 0; OPEN+DEPOSIT_PAID gate → ERR_INVALID_STATE (409) — financing.py:18,24-25
- §3.5 Booking — insert — ambiguity — pre-existing active booking on case → ERR_INVALID_STATE (409) — cases.py:189-190
- §3.6 Operate — insert — ambiguity — missing ready booking / signed consent → ERR_INVALID_STATE (409) — cases.py:317-324
- §3.6 Heal — insert — ambiguity — heal-settling period = 30 days — db.py:13
- §3.8 Enhancement create — revise — ambiguity — origin must be HEALED (ERR_INVALID_STATE 409); patient mismatch → ERR_INVALID_REQUEST (400) — enhancements.py:34-37
- §3.8 Rescreen — insert — ambiguity — screening of a different patient → ERR_INVALID_REQUEST (400) — enhancements.py:94-95
- §3.8 Enhancement adjudicate — insert — ambiguity — approve requires APPROVED re-screening else ERR_INVALID_STATE (409) — enhancements.py:127-128
- §3.9 Refund pay — insert — ambiguity — non-PAID_IN_FULL case → ERR_INVALID_STATE (409) — refunds.py:80-81

(Two of the above — Submit screening ordering and Enhancement create — are counted as the 2 revisions since they reworked existing multi-clause prose; the rest are inserts.)

**Not changed (already uniquely pinned by PRD):** flap thickness 110, optical zone 1.0mm, depth-per-diopter 12.0, round-half-up ablation, ceil installment, floored refund, guarantee fee 25000, LIFETIME window 36500, clock default 2026-05-01T00:00:00Z, all explicitly-named ERR ids in the catalogue, validation ranges the PRD already states (base_price/deposit/window/guarantee/turnaround/cap/max_daily/thickness/k_max/error/down/term/apr), OCC 412 semantics, cascade three-hop chain, and the dual-variant refund formulas.

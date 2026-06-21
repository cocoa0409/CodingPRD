# Worklog — task_0287_tuition_payment_plan

## Step 1: Create Task Directory — 2026-06-10T17:48:50.000Z

Created pre-assigned task directory `tasks/task_0287_tuition_payment_plan/` with `workspace/` subfolder. Index scan skipped per orchestrator instruction (5 entrance pipelines running in parallel; pre-assigned path used directly).

## Step 2: Generate Scaffold (EXPERT difficulty) — 2026-06-10T18:09:43.000Z

Both OCC endpoints satisfy the §1.2.1 hard contract: they take `expected_enrollment_version` as required input and bump the version in side effects.

All three files are complete, parse cleanly, pass the scaffold lint with zero violations, and meet every Expert-band and §0.5/§1.8/§1.9 requirement. The scaffold generation is done.

### Summary

Generated three scaffold artifacts at **Expert difficulty** for the Tuition Payment Plan domain, all in `tasks/task_0287_tuition_payment_plan/`.

**Archetype/profile**: Primary = Ledger reconciliation, secondary = Pricing engine; flat (`/institutions/...`) topology; parallel state-machine shape; peer_roles RBAC; immediate consistency. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency.

**SCAFFOLD.yaml (§1.0–§1.7)** — Expert band confirmed:
- **Entities: 12** — Institution, AcademicTerm, Student, PlanTemplate, Enrollment, Installment, Charge, FinancialAid, Payment, LateFee, Hold, Withdrawal (16 FKs, all reverse-reachable via filtered-list GETs).
- **State machines: 9** — AcademicTerm, Enrollment, Installment (parallel dimension + OVERDUE↔PAID), Payment, Hold, Charge, FinancialAid, LateFee, PlanTemplate. Enrollment bubble-up to COMPLETED; cross-entity guarded transitions.
- **Concurrency rules: 2** — OCC on Enrollment.version for activate and withdraw (412 / `expected_enrollment_version`, both bump version).
- **Key calculations: 6** — `installment_schedule` (round-then-floor remainder-onto-earliest), `balance_recalc_on_charge` (positive delta onto earliest / negative reduce-from-latest), `balance_recalc_on_aid`, `late_fee_assessment` (tiered clamp), `delinquency_evaluation` (count≥3 OR amount≥150000), `refund_proration` (dual variant: DATE_BASED continuous vs SCHEDULE_BASED bracket — diverge 217049 vs 90000 refund on identical inputs).
- **Validations: 12** (priority-ordered), **Errors: 21**, **Endpoints: 44** (incl. `/_clock/set_current_utc` test-driving), **Roles: 3** (Registrar/Bursar opaque, Student entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**: 9 rules × 2 instances = **18 instances**, all literals pre-computed (e.g., 122-day term, [80000×4] schedule, late fee 3200, retained 122951).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**: **29 active instances + 6 excluded_because stubs** across all 9 taxonomy sections (entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting/consistency).

**Validation**: `scaffold_lint.py` → `VERDICT: clean lint` (484 calls scanned, all conform; all FKs reverse-reachable). No forbidden concurrency vocabulary; all 21 errors referenced; all grounds resolve; no name collisions; file-split correct (no design keys in SCAFFOLD.yaml).

## Step 3: Copy Shared Files — 2026-06-10T18:10:04.000Z

Copied `INSTRUCTION.md` → `tasks/task_0287_tuition_payment_plan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T18:15:43.000Z

All Contract 2 high-risk rule coverage spot-checks pass. The PRD is complete and all three Hard Contracts pass.

### Summary

Generated `workspace/PRD.md` for the **Tuition Payment Plan API**.

**Structure:**
- 5 top-level sections (1. Introduction, 2. Global Specifications, 3. Business Logic & Workflows, 4. Endpoint Definitions, 5. Error Code Catalogue)
- 9 §2 subsections (2.1–2.9, domain-derived: institutional scoping/logical clock, versioning, precision, OCC, lifecycle consistency, conserved-principal ledger)
- 10 §3 subsections (3.1–3.10, organized by lifecycle/business-process: setup → enrollment → charges/aid → activation → re-spread → payments → delinquency/late fees → holds → withdrawal/refund → validation ordering)
- **Line count: 266**

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 63 required identifiers (entity fields + endpoint inputs + query params + path params), all present verbatim in backticks; 0 missing.
- **Contract 2 (Rule Coverage):** Both OCC rules (activate/withdraw with `expected_enrollment_version`, `ERR_STALE_VERSION`, HTTP 412); both refund-proration variants (DATE_BASED continuous, SCHEDULE_BASED 0/25/50/100% brackets at 7/21/42 days); late-fee tiers (2/4/6%) and constants (2500/2500/7500/30000); delinquency thresholds (count ≥3, amount ≥150000); installment-schedule waterfall with round-half-up-before-floor and earliest/latest re-spread; all 12 priority-ordered validations including the two layered orderings on activate and payment-settle. All formulas in precise prose, no pseudocode, no fuzzy words.
- **Contract 3 (§3 Path Purity):** 438 §3 backtick tokens scanned; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.

**Other verifications:** §2.2 byte-identical to canonical fixed block; §4 table exactly 4 columns / 44 endpoint rows; §5 table exactly 2 columns / 21 error rows; all 21 error IDs appear in §2/§3 narrative and the §5 table.

**Confirmation:** No design-index file was read. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. No sibling task was read.

## Step 5: Generate Unit Tests — 2026-06-10T18:31:49.000Z

Test infrastructure generation complete for task_0287_tuition_payment_plan. All artifacts compile and all 65 tests collect cleanly.

### Summary

**Test files:** 5 (plus `conftest.py`), **65 tests total** = 36 queue-A (difficulty) + 29 queue-B (corner).

- `test_01_schedule_and_pricing.py` (12) — installment schedule rounding, dual-variant refund proration, late-fee tiers, effective-date clamp
- `test_02_delinquency_and_holds.py` (11) — delinquency thresholds, hold reason/boundary, transitive cascades, late-fee compensating invariant
- `test_03_lifecycle_and_state.py` (10) — parallel installment axis, charge POSTED→REVERSED recalc, principal-conservation invariant, state-machine transitions
- `test_04_activation_guards.py` (15) — validation-priority pairs, cross-entity gates, enroll-window boundary, OCC version/stale-version
- `test_05_crud_validation_rbac.py` (17) — creation/defaults/computed fields, validation errors, payment fiscal rules, listing, RBAC

**Queue A (Difficulty): 18/18 instances translated, each with exactly 2 tests** (skill minimum ≥2 met). All 9 rules covered: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. No skips — every instance has verbatim PRD coverage and is uniquely derivable. Priority-pair instances got a control-test partner (remove the higher-priority violation → confirm the lower-priority error surfaces), which proves the ordering from PRD §3.10.

**Queue B (Corner): 29/29 non-stub instances translated (1 test each); 6 `excluded_because` stubs correctly NOT translated.** All 6 stub `difficulty_instance` cross-references verified to resolve to real queue-A instances.

**test_helpers/ files emitted (9):** `__init__.py`, `types.py`, `api_client.py` (one method per endpoint), `api_errors.py` (21 errors + HTTP-status map registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Registrar/Bursar opaque, Student entity-backed with `make_student_headers`), `fixtures.py` (composite helpers: base scaffolding, pending/active enrollment, delinquent-enrollment, payment settlement, withdrawal).

**Validation performed:** all helper + test modules byte-compile; full suite collects 65 tests with a stub framework (no broken helper references); every PRD citation verified to have a verbatim ≥8-word window in PRD.md (the 2 flagged were ellipsis-joined multi-sentence citations whose fragments are each verbatim — permitted by the skill).

One PRD-derivability note worth flagging for downstream: the refund `refund_to_student_cents`/`net_owed_after_withdrawal_cents` and late-fee tier values are pinned to the design YAML's pre-computed literals, all of which I re-derived from PRD §3.7/§3.9 prose and confirmed consistent (e.g. DATE_BASED day-30 retained 122951 → refund 217049; 36-days-late 6% → 4800).

## Step 6: Generate Implementation — 2026-06-10T18:31:49.000Z

All 44 routes register (matching the 44 endpoints in the PRD table), the store is empty at import (all 12 entity dicts length 0), and there's no seeding logic. The implementation is complete and verified.

### Summary

Generated a complete Python + Flask implementation of the Tuition Payment Plan API in `workspace/implementation/`.

**Source files emitted (25 total):**
- `start.sh` (foreground launcher, reads `$PORT` default 10000, binds `0.0.0.0`, guards pip install on `import flask`, `exec python3 app.py`), `requirements.txt` (flask==3.0.3)
- `app.py` (entry point, blueprint registration, ApiError + 404/405/500 handlers), `db.py` (12 in-memory dicts, UUID ids, `stamp_new`/`touch` for created_at/updated_at/version), `errors.py` (21-entry error catalog), `response.py` (meta/response_type/data envelope, `req_` ids, ISO-8601 UTC 3-fractional-digit timestamps, pagination fields in meta), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role gate)
- `routes/` (12 files): institutions, terms, students, plan_templates, enrollments, installments, charges, aids, payments, late_fees, holds, withdrawals
- `services/` (7 files): dates (logical-clock day math), calc (all calculations), domain (recompute/delinquency/hold helpers), serialize, listing, validate

**Endpoint count:** 44 routes registered, matching the PRD §4 endpoint table exactly.

**State machines implemented:** AcademicTerm (OPEN→LOCKED→CLOSED with open-balance guard), Enrollment (PENDING→ACTIVE→COMPLETED/WITHDRAWN), Installment (SCHEDULED→PAID/OVERDUE, OVERDUE→PAID), Payment (PENDING→SETTLED/FAILED), Hold (ACTIVE→RELEASED, manual + auto), Charge (POSTED→REVERSED), FinancialAid (APPLIED→CANCELLED), LateFee (ASSESSED→WAIVED), PlanTemplate (ACTIVE→RETIRED). Cascades implemented: installment-PAID bubbles enrollment to COMPLETED; withdrawal cancels installments + releases hold; curing delinquency clears hold; derived-field recomputes bump enrollment version.

**Calculations implemented:** installment_schedule (round-half-up down payment first, then floor+earliest-remainder split, cadence = floor(total_days/(N+1))), balance_recalc on charge/aid (positive delta onto earliest SCHEDULED, negative reduces from latest, `ERR_NO_SCHEDULED_INSTALLMENTS` guarded atomically), late_fee_assessment (day-based 2/4/6% tiers, flat floor 2500, clamp 2500–7500, 30000 per-enrollment cap), delinquency_evaluation (count≥3 OR amount≥150000 thresholds), refund_proration (DATE_BASED continuous and SCHEDULE_BASED 0/25/50/100% bracket variants, with net-owed and refund-to-student settlement). All money is integer cents via `decimal.Decimal` round-half-up.

**Validation ordering** follows PRD §3.10 (header → role → existence → body → state → hold → term/window → autopay → charges → OCC), and OCC uses `expected_enrollment_version` (412 `ERR_STALE_VERSION`) on activate/withdraw only.

**Storage confirmation:** All state is in-memory only (12 module-level dicts in `db.py`); a fresh import yields all dicts empty, no `seed_*`/preload/hardcoded entities anywhere — every byte of state is wiped on `start.sh` re-invocation. Verified end-to-end via four ad-hoc HTTP test suites (happy-path lifecycle, delinquency/holds, balance re-spread, both refund variants, late-fee cap, RBAC, and validation ordering) — all pass when booted through `start.sh` with `$PORT`.

## Step 7: Run Tests and Iterate — 2026-06-10T18:38:54.000Z

All 8 parallel rounds pass cleanly (65/65 each, zero failures, zero errors). Exiting with the summary.

### Summary

**Iterations run:** 2 (initial sweep surfaced 3 consistent failures across all 8 rounds; second sweep after fixes was clean — 65/65 in every round).

**Tests deleted:** None. All three failures were diagnosed as test bugs (assertions/setup contradicting the PRD), fixable to be MORE faithful to PRD; no test was PRD-silent or non-uniquely-derivable in a way requiring deletion.

**Fixes applied to test_suite/** (no test_helpers/ or implementation/ changes were needed — the implementation was already PRD-faithful):

1. `test_suite/test_03_lifecycle_and_state.py` :: `test_charge_reversal_respread_reduces_latest_installments` — The test asserted the post-then-reverse cycle restored `[80000, 80000, 80000, 80000]`, but PRD §3.5's negative-delta rule ("walks the scheduled installments from the *latest* sequence index backward, reducing each installment's `amount_cents` by as much of the remaining credit as that installment holds … stopping once the credit is exhausted — reductions come off the *latest* installments first") uniquely yields the greedy latest-first walk: the entire 60000 credit comes off installment 4 (95000→35000), giving `[95000, 95000, 95000, 35000]`. Fixed the assertion and the docstring (which had misstated the rule's outcome) to match the PRD-literal behavior the implementation correctly produces.

2. `test_suite/test_03_lifecycle_and_state.py` :: `test_charge_post_then_reverse_restores_per_installment_amounts` — Same root cause: docstring falsely claimed per-line schedule conservation across the asymmetric post (base-spread onto earliest) / reverse (greedy latest-first) operations. Fixed the assertion to `[95000, 95000, 95000, 35000]` and added a sum-conservation check (`== 320000`), and corrected the docstring to state that the financed-principal *sum* is conserved while per-line amounts diverge — the PRD's actual guarantee.

3. `test_suite/test_05_crud_validation_rbac.py` :: `test_settle_installment_after_paid_rejected` — The setup used a 1-installment, zero-down plan; paying that single installment drove the enrollment `ACTIVE → COMPLETED` via PRD §3.6's auto-completion bubble, so the re-settle attempt correctly tripped the earlier-priority `ERR_ENROLLMENT_NOT_ACTIVE` (PRD §3.6 orders the enrollment-ACTIVE guard before the installment-payability check) instead of the intended `ERR_INSTALLMENT_NOT_PAYABLE`. Fixed the fixture setup to use a 2-installment plan and pay by `inst["amount_cents"]`, leaving a second SCHEDULED installment open so the enrollment stays ACTIVE (completion bubble doesn't fire) and the re-settle cleanly reaches the installment-payability check — isolating the rule the test intends to verify.

**Note on the precedence case:** The third failure was a true two-reading ambiguity (whether a zero down payment is "collected by construction" per PRD §3.6, which is silent on zero-down collection). Rather than relax to `validate_error_is_one_of`, the setup was reworked so the scenario is unambiguous under either reading (enrollment provably stays ACTIVE), preserving the exact-`error_id` assertion.

**Final verification:** all 8 results.{1..8}.json show passed=65 total=65.

## Step 8: Finalize PRD — 2026-06-10T18:41:55.000Z

The single edit is in place. Let me produce the exit summary.

### Summary

**PRD.md vs PRD_FINALIZED.md:** 265 lines → 265 lines (0% line-count delta; one line revised in place, no lines added/removed).

#### Changes (one bullet per change)

- **§3.6 (Collecting Payments / completion bubble)** — *revise* — Pinned that the auto-completion bubble treats a **zero** `down_payment_cents` as collected-by-construction (no settled `DOWN_PAYMENT` payment required), while a positive down payment still requires an actually-settled `DOWN_PAYMENT`. — `services/domain.py:162-168` (`down_payment_settled`), consumed by `services/domain.py:171-188` (`maybe_complete`).

#### Per-edit pre-edit search log

**Edit 1 — §3.6 completion bubble, zero-down "collected by construction"**

- **(a) Subject identified:** What it means for "the down payment has been collected" in the `ACTIVE → COMPLETED` completion-bubble precondition, specifically for a zero down payment.
- **(b) Impl paths enumerated / read:**
  - `services/domain.py:162-168` `down_payment_settled` — zero `down_payment_cents` → `True` by construction; positive → requires the `down_payment_collected` flag. This is the ONLY consumer of the distinction.
  - `services/domain.py:171-188` `maybe_complete` — the sole completion path; gates on `down_payment_settled`.
  - `services/domain.py:71-80` `recompute_paid_principal` — adds `down_payment_cents` only when the `down_payment_collected` flag is set; for a zero down payment this adds 0 either way, so `paid_principal_cents` is identical under both readings (no conflict with my edit, which scopes the by-construction rule to the completion check only).
  - `routes/payments.py:104-113` DOWN_PAYMENT settle — sets `down_payment_collected = True`, second settle → `ERR_DOWN_PAYMENT_ALREADY_PAID`; independent of the zero/positive distinction, untouched by my wording.
  - `routes/payments.py:113,140` — both `maybe_complete` callsites (after DOWN_PAYMENT settle and after installment settle); both flow through the same helper, so no parallel completion path exists.
- **(c) Wording adjustment:** Scoped the new clause explicitly to "this completion check" so it does not bleed into the adjacent `paid_principal_cents` sentence ("plus the `down_payment_cents` once it has been collected") or the `ERR_DOWN_PAYMENT_ALREADY_PAID` settlement rule — both of which key off the literal `down_payment_collected` flag and remain accurate as written. This keeps every enumerated path consistent.

#### Items deliberately NOT patched

- **step_7_diff items 1 & 2** (`test_charge_reversal_respread_reduces_latest_installments`, `test_charge_post_then_reverse_restores_per_installment_amounts`): PRD §3.5 already uniquely determines the negative-delta latest-first greedy walk verbatim ("walks the scheduled installments from the *latest* sequence index backward … reductions come off the *latest* installments first"), and `services/calc.py:54-75` `respread_delta` matches it exactly. These were pure test/docstring bugs, not PRD silence — prose kept verbatim.
- **step_7_diff item 3** (`test_settle_installment_after_paid_rejected`): The fixture-setup portion (2-installment plan to keep the enrollment ACTIVE) was a test-fixture fix, not a PRD silence. The only genuine PRD gap underlying it — zero-down "collected by construction" — is captured by Edit 1 above.

## Step 9: Complete PRD — 2026-06-10T18:48:07.000Z

All edits are in-paragraph; exactly 10 lines (paragraphs) revised, no lines added/removed, no new sections. PRD_COMPLETED.md is produced.

**PRD_COMPLETED.md — completion summary (task_0287_tuition_payment_plan)**

- **Source vs completed:** `PRD_FINALIZED.md` 265 lines / 46,908 chars → `PRD_COMPLETED.md` 265 lines / 51,077 chars (+4,169 chars; 0 lines added/removed — all changes are in-paragraph inserts/revisions).
- **Counts:** ambiguity-pins: 9, mismatch-revisions: 1. (10 paragraphs touched.)

Per-change bullets:

- §2.3 Pagination — insert — ambiguity — pinned silent clamping (out-of-range numeric `limit`/`offset` clamped, not rejected; non-integer → `ERR_INVALID_REQUEST`) and the optional per-resource equality-filter query params (`status` + FK fields) with unknown params ignored — `services/validate.py:60-87`, `routes/terms.py:83-89`, `routes/enrollments.py:85-97`, `routes/holds.py:31-40`, etc.
- §3.1 Institution/clock — insert — ambiguity — pinned `currency` (non-empty, default USD), `refund_policy` invalid → `ERR_INVALID_REQUEST`, invalid `to_iso8601` → `ERR_INVALID_REQUEST`, and that clock-set returns the institution at 200 and bumps `updated_at`/`version` — `routes/institutions.py:23-66`.
- §3.1 Term code — insert — ambiguity — pinned duplicate `OPEN`/`LOCKED` term code → `ERR_INVALID_REQUEST` — `routes/terms.py:51-54`.
- §3.1 PlanTemplate — insert — ambiguity — pinned `down_payment_pct` int-or-float; type/sign violations (non-int `installment_count`/`plan_fee_cents`, non-numeric `down_payment_pct`, negative `plan_fee_cents`, bad `late_fee_grace_days`) → `ERR_INVALID_REQUEST` (vs range → `ERR_INVALID_PLAN_TEMPLATE`) — `routes/plan_templates.py:29-51`.
- §3.2 Student — insert — ambiguity — pinned duplicate `external_ref` → `ERR_INVALID_REQUEST` and `email` accepted without format validation — `routes/students.py:33-35`.
- §3.3 Charge posting — insert — ambiguity — pinned that the `has_active_hold` gate (`ERR_STUDENT_ON_HOLD`) is checked after field validation and before the §3.5 re-spread guard — `routes/charges.py:37-45`.
- §3.6 Payment creation — insert — ambiguity — pinned: `installment_id` ignored/null for `DOWN_PAYMENT`; required-non-string → `ERR_INVALID_REQUEST` and non-matching → `ERR_NOT_FOUND` for `INSTALLMENT`/`AUTOPAY`; `Student` ownership → `ERR_FORBIDDEN_FOR_ROLE`; payment creatable in `PENDING` regardless of enrollment status (ACTIVE enforced only at settle) — `routes/payments.py:29-59`.
- §3.7 Delinquency — revise — mismatch — PRD's "the same effect can occur on a clock advance handled by the system" contradicted impl (clock-set never sweeps); revised to state overdue transitions occur only via explicit run-delinquency, sweep walks ascending `sequence_index`, endpoint always 200, version advances only when something is swept — `routes/institutions.py:52-66`, `routes/enrollments.py:256-305`.
- §3.9 Withdrawal — insert — ambiguity — pinned missing/non-integer `expected_enrollment_version` → `ERR_INVALID_REQUEST`, missing/unparseable `effective_date` → `ERR_INVALID_REQUEST`, and check order: state → effective_date → version guard — `routes/enrollments.py:199-231,308-315`.
- §3.10 Activation ordering — insert — ambiguity — pinned retired-template check (`ERR_TEMPLATE_RETIRED`) position (immediately after window, before autopay), autopay-before-charges order, version guard last, and missing/non-integer version → `ERR_INVALID_REQUEST` evaluated only after all other preconditions pass — `routes/enrollments.py:129-152,308-315`.

Note (not patched, deliberately): the impl additively serializes `institution_id` on child resources (serialize.py) — purely additive, not a PRD-stated field set restriction, and test `types.py` omits it; left unpinned to avoid inventing constraints. Partial-installment-settlement version bumps are already covered by §2.5's "a derived-field recomputation counts as a mutation."

---

## Pipeline Complete — 2026-06-10T18:48:07.000Z

All 9 steps complete. Final state: 65/65 tests pass across all 8 stability rounds. Task artifacts: SCAFFOLD.yaml (+ 2 design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (5 files + conftest), workspace/implementation/ (25 source files, in-memory Flask).

# Worklog — task_0159_optometry_vision_plan

## Step 1: Create Task Directory — 2026-06-05T00:54:26.000Z

Created `tasks/task_0159_optometry_vision_plan/` and `tasks/task_0159_optometry_vision_plan/workspace/` via `mkdir -p`. Pre-assigned index 0159 used per orchestration directive (auto-scan overridden; three sibling pipelines concurrently creating 0158–0161). Confirmed no prior `task_0159_*` directory existed before creation.

## Step 2: Generate Scaffold (Expert) — 2026-06-05T01:16:04.000Z

Generated a fresh **Expert-tier** scaffold for the Optometry & Vision Plan scenario. All three files written to `tasks/task_0159_optometry_vision_plan/` and `scaffold_lint.py` returns **VERDICT: clean lint**.

**Entities (10):** Patient, Encounter, Provider, Prescription, Eligibility, BenefitPool, LabOrder, Claim, RecallReminder, ClockState. Topology is **flat** (FK-linked peers, `api_prefix: ""`).

**State machines (6):**
- Encounter — linear pipeline with void branch (OPEN→REFRACTED→FINALIZED / OPEN→VOIDED)
- Prescription — supersede + expiry + revoke (ACTIVE→SUPERSEDED/EXPIRED/REVOKED)
- **LabOrder — cyclic remake loop** (DISPENSED→REMAKE_REQUESTED→IN_LAB→DISPENSED), non-linear
- **Claim — parallel dimensions** (claim_status DRAFT→ADJUDICATED→SETTLED × submission_status UNSUBMITTED→SUBMITTED→ACCEPTED/REJECTED evolving independently)
- Eligibility — drawdown lifecycle with EXHAUSTED↔ACTIVE bubble-up
- RecallReminder — linear outreach with cross-entity FULFILLED

**Counts:** 5 calculations (dual-variant routine-vs-medical billing on Claim; provisional-vs-final materials draw on LabOrder; round-then-sum statement; remake surcharge threshold; recall date) · 15 validations (priority-ordered) · 46 endpoints · 15 error codes · 4 roles (FrontDesk, Optometrist[entity_backed:Provider], Optician[entity_backed:Provider], Biller) · 1 concurrency rule (OCC on Eligibility.version for benefit-drawing LabOrder create).

**Difficulty tier:** Expert — Ledger-reconciliation primary archetype + Compliance/audit secondary; layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, derived_field_reconciliation. Tight coupling: LabOrder draws cross-aggregate against Eligibility's BenefitPool; Claim spans Encounter+Eligibility; cancel/void cascades reconcile conserved quantities.

**§1.8 (depth):** 9 rules × 2 = **18 instances**, all grounds resolve, all OCC versions use `${var}`, formula-derived asserts pre-computed (verified by executing the formulas — e.g. ROUTINE patient_responsibility 2500, MEDICAL plan_paid 14400, round-then-sum 5200 vs wrong 5100, +90-day remake boundary 2026-08-30 inclusive).

**§1.9 (breadth):** 9 taxonomy sections, **40 instances** = 34 active + 6 `excluded_because` stubs (each citing a real §1.8 instance). All 393 setup/trigger calls conform to §1.5; all names unique across both files.

Fixed during generation: YAML flow-sequence `?`/`[` quoting in inputs/grounds/captures, a self-pay remake-surcharge assert (25500 not 5500), an unbound `${order_id}` in the DESIGNER-tier corner assert, the materials final-recompute reconciliation formula made explicit, and a `GET /benefit-pools` filtered-list added for BenefitPool→Eligibility FK reverse-reachability.

Files: SCAFFOLD.yaml (1484 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1148 lines), SCAFFOLD_CORNER_DESIGN.yaml (1318 lines).

## Step 3: Copy Shared Files — 2026-06-05T01:16:04.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0159_optometry_vision_plan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T01:23:51.000Z

Generated `workspace/PRD.md` — **269 lines** — from the optometry-vision-plan scaffold.

### Section list
- **1. Introduction** (ledger reconciliation, compliance, simulated-clock angles)
- **2. Global Specifications & System-Wide Principles** — 2.1 RBAC (4 roles; Optometrist/Optician entity-backed to Provider, FrontDesk/Biller opaque), 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties and the Simulated Clock, 2.5 Nested Resource Retrieval and Reference Validation, 2.6 Validation Ordering, 2.7 Monetary Amounts/Precision/Rounding, 2.8 Benefit-Pool Reconciliation and Derived Balances, 2.9 Hierarchical Consistency and Cascading Side Effects, 2.10 Optimistic Concurrency on Benefit Draws
- **3. Business Logic & Workflows** (10 subsections by entity lifecycle)
- **4. Endpoint Definitions** (46 endpoints, 4-column table)
- **5. Error Code Catalogue** (15 errors)

### Hard Contract results (mechanically verified by subagent)
- Contract 1 (Field-Name Coverage): PASS — 56/56 entity fields, 8/8 input/query identifiers, 9/9 path params, 4/4 common fields.
- Contract 2 (Rule Coverage): PASS — OCC stale-version (`expected_eligibility_version` + `ERR_STALE_ELIGIBILITY_VERSION` HTTP 412), priority-ordered validations, dual-variant claim calc (routine copay vs medical 80% coinsurance + non-covered refraction), provisional-vs-final materials draw (frame cap 13,000 cents × tier × min(desired, available)), round-then-sum statement, remake surcharge (≥2 → 2,500 cents), cross-entity cascades, expiry 24/12 months, all transitions+error pairings.
- Contract 3 (§3 Path Purity): PASS — 393 §3 backtick tokens, 0 endpoint paths/methods leaked.

Confirmed: subagent did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-05T01:40:22.000Z

Generated complete test infrastructure from the two design indices only (no freelance SCAFFOLD walking).

### Test files (test_suite/) — 6 files + conftest, 70 test functions
- `test_01_claim_adjudication_costs.py` (5) — routine vs medical claim cost, statement round-then-sum
- `test_02_materials_cost_and_draw.py` (6) — tiered frame cap, provisional vs final draw reconciliation
- `test_03_state_machines.py` (10) — remake loop, parallel claim dimensions, lifecycle/terminal transitions
- `test_04_cascades_and_invariants.py` (10) — cancel/void cascades, recall fulfillment, compensating invariants
- `test_05_validations_and_boundaries.py` (23) — priority conflicts, boundary precision, cross-entity deps, corner validations
- `test_06_entities_endpoints_rbac.py` (16) — CRUD/schema, system fields, immutability, listing, RBAC

### Queue counts
- Queue A (Difficulty): 36 tests — all 18 instances covered ≥2 tests each.
- Queue B (Corner): 34 tests — all 34 non-stub instances covered exactly 1 test each.

### Skipped instances: 0 non-stub instances skipped
- Every Queue A and Queue B non-stub instance passed the PRD-first two-condition filter.
- The 6 `excluded_because:` corner stubs correctly NOT translated; all 6 cross-refs resolve to real difficulty instances.

### test_helpers/ files written (9)
`__init__.py`, `api_client.py` (all 40 endpoints), `api_errors.py` (15 errors; ERR_INVALID_REQUEST→422), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (entity_backed Provider identity threading), `test_users.py`, `types.py` (Provider/ClockState common_fields:false — no version).

Note: framework not importable in generation shell; tests validated by AST parse + static name-resolution. Runtime import succeeds under runner PYTHONPATH.

## Step 6: Generate Implementation — 2026-06-05T01:40:22.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

### File list
- `start.sh`, `requirements.txt` (flask==3.0.3), `app.py` (blueprints, error handlers, `app.run(host="0.0.0.0")`)
- `db.py` (in-memory store, dicts keyed by id), `clock.py` (simulated clock, ISO-8601 ms, add_months), `errors.py` (ApiError + 15 ids), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `helpers.py` (pagination, round-half-up Decimal, validators), `serialize.py` (live computed fields)
- `routes/` — clock_routes, providers, patients, encounters, prescriptions, eligibilities, lab_orders, claims, recall_reminders
- `services/` — benefit, materials, claim_calc, patient_balance

### Storage / boot
Purely in-memory single `Store` instance, one dict per entity type, server-minted UUID keys. No SQLite/JSON/tmp. Store constructed at module load → every start.sh re-invocation = brand-new empty store. start.sh: `cd $(dirname)`, guards pip behind `import flask` check, `exec python3 app.py`; app reads `PORT` env (default 10000), binds `0.0.0.0` foreground threaded.

### No seeding — confirmed
Brand-new process reports total_count=0 for all nine list endpoints; no seed_* function. Subagent ran 80+ self-check assertions across four end-to-end suites — all pass (auth/RBAC/path/reference precedence, routine/medical claim math, materials draw + frame cap + clamping, provisional-vs-final recompute, EXHAUSTED↔ACTIVE bubble-up, OCC 412, remake loop + surcharge + 90-day window, Rx expiry gating, void restoring exam benefit, recall fulfillment, round-then-sum statement, pagination).

## Step 7: Run Tests and Iterate — 2026-06-05T01:47:42.000Z

**Iterations run:** 2 sweeps (1 baseline diagnostic + 1 verification). Final 8-round parallel sweep: all 8 rounds pass 70/70.

**Baseline:** 2 stable failures (failed in all 8 rounds, both in `test_05_validations_and_boundaries.py`). Both were STEP-2 test bugs: the test fixtures constructed preconditions the PRD-faithful implementation correctly rejected during setup. No tests deleted; no implementation changes.

**Tests deleted:** None. Both failing tests asserted rules that PRD verbatim-covers and uniquely determines (STEP 1 passed for both).

**Fixes applied to test_suite/** (`test_05_validations_and_boundaries.py`):

1. `test_dispense_blocked_by_revoked_prescription` → renamed to `test_dispense_blocked_by_non_dispensable_prescription`. The original setup placed an order, sent it to lab (IN_LAB), then tried to **revoke** the prescription — but PRD §3.3 states "Revocation is permitted only when the prescription is `ACTIVE` and no lab order in `PLACED` or `IN_LAB` status references it," so the IN_LAB order correctly blocks the revoke (`ERR_INVALID_STATE`). The revoked-Rx-with-IN_LAB-order state the test wanted is unreachable under PRD. Fixed the setup to drive the prescription to the **SUPERSEDED** terminal state instead (issue a fresh ACTIVE EYEGLASS Rx of identical `rx_type` from a new encounter, per PRD §3.3), which reaches the same non-dispensable state without touching the order. The asserted PRD rule (dispense of a non-ACTIVE prescription → `ERR_PRESCRIPTION_NOT_DISPENSABLE`, PRD §3.6/§3.5) is preserved exactly — error assertion unchanged.

2. `test_medical_billing_ineligible_non_h_complaint`. The original built a MEDICAL_EYE encounter with a non-H code (`Z01`), called `draft_claim(...)` in setup (lenient `get_success_data`), and asserted the error at **adjudicate**. But PRD §3.8's medical-eligibility rule lives in the *drafting* paragraph ("A `Biller` bills... by drafting a claim... a medical claim that fails either condition is rejected with `ERR_MEDICAL_BILLING_INELIGIBLE`"), and the implementation correctly rejects the **draft** — so the draft-succeeds-then-adjudicate-fails path the test assumed is unreachable. Fixed the test to issue `create_claim` directly and assert `ERR_MEDICAL_BILLING_INELIGIBLE` on the draft response (the actual PRD-mandated rejection point). Exact error_id assertion unchanged.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None. Both implementation behaviors (revoke-blocking in `routes/prescriptions.py`, medical-eligibility check at draft in `routes/claims.py`) were already PRD-faithful and were preserved.

## Step 8: Finalize PRD — 2026-06-05T01:49:53.000Z

Ran (not skipped — Step 7 had 2 test_suite/ fixes and 2 sweeps, so the 4-way zero skip condition was not met). Outcome: **zero edits**. `PRD_FINALIZED.md` is byte-identical to `PRD.md` (269 lines, 0.0% delta; `diff -q` confirms IDENTICAL).

Both `<step_7_diff>` items are pure test-fixture bugs where the implementation was already PRD-faithful and PRD already verbatim-covers and uniquely determines the behavior — no PRD-silence and no PRD/impl mismatch to pin.

**Per-subject pre-edit search log:**
- Subject 1 — Prescription revocation gating / non-dispensable terminal states. Enumerated `routes/prescriptions.py:151-169` (revoke gate), `serialize.py:91-100` (effective_rx_status), `routes/lab_orders.py:25,55-61,196-207` (dispensability gate → ERR_PRESCRIPTION_NOT_DISPENSABLE), `routes/prescriptions.py:87-93` (supersede cascade). All consistent with PRD §3.3/§3.5/§3.6. Fixture's revoked-Rx-with-IN_LAB state genuinely unreachable; PRD uniquely determines. No edit.
- Subject 2 — Medical billing eligibility checked at draft. Enumerated `routes/claims.py:19-24` (_medical_eligible), `:50-58` (draft rejects MEDICAL with ERR_MEDICAL_BILLING_INELIGIBLE), `:120-124` (adjudicate re-check), `errors.py:26,76-77` (→422), encounter/serialize sources. Consistent with PRD §3.8 (rejection in drafting paragraph; re-checked at adjudication). Fixture's draft-succeeds-then-adjudicate-fails path unreachable. No edit.

## Step 9: Complete PRD — 2026-06-05T01:54:18.000Z

Full PRD-vs-implementation scan. Source: `PRD_FINALIZED.md` (269 lines, 44,690 chars). Output: `PRD_COMPLETED.md` (269 lines, 44,935 chars; +245 chars, both edits in-paragraph, no line-count change).

**Counts:** 1 ambiguity-pin, 1 mismatch-revision.

**Changes:**
- §3.4 (Opening a Vision Benefit Period and Its Pools) — insert — ambiguity — PRD described the `EXAM` pool as the routine-exam benefit slot but never stated its `allotted_cents`; pinned to fixed value 1 — `routes/eligibilities.py:17,77` (`EXAM_POOL_ALLOTTED = 1`).
- §3.3 (Writing, Superseding, Expiring, and Revoking Prescriptions) — revise — mismatch — PRD opening sentence said the source encounter "must be in `REFRACTED` or `FINALIZED` status," contradicting the later same-section sentence about issuing the first Rx from an `OPEN` encounter; revised to admit `OPEN`/`REFRACTED`/`FINALIZED` (rejecting `VOIDED` with `ERR_INVALID_STATE`) — `routes/prescriptions.py:60-68`.

Left unchanged (PRD already pins impl behavior): lab-order business-gate ordering (§3.5), materials draw/frame-cap formula (§3.5/§3.6), remake 90-day window + surcharge timing (§3.6), routine/medical adjudication math + rounding (§3.8), statement per-line dollar rounding (§3.10), in-period inclusivity (§3.4), patient-balance roll-up (§3.8), cancel-zero-draw version bump (§3.6).

## Final Verification Sweep — 2026-06-05T01:54:18.000Z

Step 7's final-sweep `results.{1..8}.json` evidence files had been cleaned from `workspace/implementation/`, so the orchestrator re-ran one confirmatory 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, --timeout 120, --test-timeout 30) to regenerate the required artifacts and independently verify. **Result: all 8 rounds 70/70 passed, 0 failed.** `results.{1..8}.json` now present.

## Pipeline complete — all 9 steps done. 70/70 tests pass across 8 parallel rounds.

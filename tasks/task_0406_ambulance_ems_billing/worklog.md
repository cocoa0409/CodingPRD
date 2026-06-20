# Worklog — task_0406_ambulance_ems_billing

## Step 1: Create Task Directory — 2026-06-18T12:26:07.000Z

Task directory pre-allocated by user: `tasks/task_0406_ambulance_ems_billing/` with `workspace/` subdir. No auto-increment scan performed (directory used as-is per user instruction).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-18T12:54:50.000Z

All three Expert-tier scaffold artifacts generated for task_0406_ambulance_ems_billing (Ambulance & EMS Billing / NEMSIS ePCR). All files pass `scaffold_lint.py` with **`VERDICT: clean lint`** (524 §1.8/§1.9 calls checked, all FK reverse-reachability satisfied).

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1363 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) — 1351 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) — 1665 lines

**Complexity profile:** Ledger-reconciliation primary archetype + Compliance/audit secondary; flat entity topology; parallel state-machine shape; peer_roles. Layers: dual-variant calculation, cascading side effects, optimistic concurrency, derived-field reconciliation, rate/threshold triggers.

**Scale (Expert tier):** 13 entities, 44 endpoints, 3 state machines, 10 calculations, 32 validations, 33 errors, 5 roles, 1 concurrency rule.

**Key mechanics:**
- **Entities:** Agency, AgencyStaff, PayerPlan, Patient, Vehicle, CrewMember, UnitAssignment, Transport, Charge, Claim, RemittanceLine, Payment, Adjustment.
- **State machines:** Transport carries two *parallel* dimensions (`documentation_status` IMPORTED→CODED→NECESSITY_REVIEW↔RETURNED→DOCUMENTATION_COMPLETE, and `billing_status` UNBILLED→BILLING_IN_PROGRESS→BILLED→PATIENT_BALANCE→CLOSED/VOID); Claim is *cyclic* (SUBMITTED→DENIED→APPEALED→SUBMITTED). The billing dimension includes a genuine CREATE-with-supersede self-loop (primary rebill) that legitimizes the OCC race per §1.2.1.
- **Calculations:** dual-variant `adjudicated_allowed` (Claim domain) and `patient_responsibility` (Transport domain: standard balance-bill vs No-Surprises protected); `compute_charge_billed_amount` pins round-per-tier-then-sum for rural mileage bonus; `charity_writeoff` uses a 3-input FPL test; `reconcile_transport_ledger` pins evaluation order. All asserts pre-computed as literals.

**Difficulty design coverage:** all 9 §0.5 rules × 2 instances = 18 instances, each with a distinct distinguishing_aspect.
**Corner design coverage:** 37 instances across 7 sections (32 active test recipes + 5 `excluded_because` stubs).

## Step 3: Copy Shared Files — 2026-06-18T12:55:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0406_ambulance_ems_billing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T13:04:45.000Z

(First attempt died on a mid-response connection error before writing any file; retried fresh.)

Generated `workspace/PRD.md` — 291-line / ~7,150-word PRD for Ambulance EMS Billing (NEMSIS ePCR), Expert tier.

**Structure**
- §1 Introduction — ambulance billing lifecycle, dual-dimension state, ledger reconciliation themes.
- §2 Global Specifications — 9 subsections: RBAC (5 roles), verbatim envelope, pagination, common resource props, hierarchical consistency/cascades/path validation, monetary precision, OCC on claim submission, parallel transport state model, reference-data lifecycle gates.
- §3 Business Logic — 11 subsections scattering rules: agency/staff/fleet setup, unit scheduling (vehicle closed+buffer vs crew half-open overlap), run import + LOS coding, documentation lifecycle + revision loop, voiding, claim submission + payer sequencing + primary rebill/supersede, remittance adjudication (dual-variant allowed), denial-appeal-resubmit loop + auto billing advancement, payments + pinned-order ledger reconciliation, write-offs (charity FPL test, No Surprises cap, discretionary), validation priority ordering.
- §4 — 44-endpoint table; §5 — 33-error table.

**Coverage (verified programmatically):** Contract 1 (field names) 68/68; Contract 2 (rules) all 8 calculations + both state machines + cyclic Claim machine + OCC rule; Contract 3 (§3 path purity) 0 violations; 60/60 state/enum values present.

**One scaffold defect corrected:** billing state-machine void note references `ERR_TRANSPORT_NOT_VOIDABLE`, absent from authoritative `errors[]` catalog; governing validation (priority 10) uses `ERR_INVALID_BILLING_STATE`. PRD §3.5/§5 use `ERR_INVALID_BILLING_STATE` to stay faithful to the catalog.

## Step 5: Generate Unit Tests — 2026-06-19T00:00:00.000Z

Generation complete. Here's the summary.

## What was done

Generated the complete test infrastructure for `task_0406_ambulance_ems_billing` under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0406_ambulance_ems_billing/`.

**Stage 1 — `test_helpers/`** (9 files): PRD-specific `types.py` (13 entity TypedDicts + 14 enums — all entities are `common_fields: true`), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (32 error IDs registered with the framework status map), `assertions.py`, `factories.py` (input-fields-only payloads), `constants.py` (fee-schedule / FPL / rounding constants), `test_users.py` (opaque `BillingAdmin` constants + per-instance `make_<role>_headers` builders for the four entity-backed `AgencyStaff` roles), and a large `fixtures.py` of composite setup chains (org bootstrap with identity-threaded staff, documentation-complete walk, claim/remittance lifecycle, PATIENT_BALANCE targeting, fleet helpers).

**Stage 2 — `test_suite/`** (conftest + 6 domain-language files, **68 tests**).

## Coverage (design-index-only)

- **Queue A (Difficulty):** all **18** instances covered, each with exactly **2** tests (`Design: Difficulty/...` tags).
- **Queue B (Corner):** all **32** non-stub instances covered with ≥1 test each (`Design: Corner/...` tags). All **5** `excluded_because:` stubs correctly skipped (cross-references verified to resolve; no placeholders emitted).

## Verification passed

- All 9 helper + 6 suite files `py_compile` clean.
- Full pytest collection (against a stub framework) succeeds: 68 tests, zero import/fixture errors.
- All 10 spot-checked PRD citations survive a literal `grep` of `PRD.md` (C1).
- No banned scaffold references (`scaffold`/`§1.x`/`Table N`) and no `skip`/`skipif`/`xfail` markers in generated code.
- All pre-computed literals independently re-derived from PRD prose (e.g. rural mileage 49875, total 94875; SCT 144000; Medicare allowed 50600; Medicaid 36640; charity 200%-boundary; No-Surprises cap 40280 → resp 12144).

## One PRD-first carve-out worth flagging

Difficulty instance `compensating_invariant/payer_payments_conserve_against_claim_paid_amounts` carries an internally-inconsistent literal: its setup payload codes a **BLS-emergency** 20mi rural transport (`emergency_indicator: true` → A0429, billed **109875**), but its `patient_responsibility_cents == 16640` assertion was computed assuming the annotation's billed 94875. A faithful PRD-only implementer arrives at 23040, so that single assertion fails unique-derivability and was **omitted**. The instance's actual conserved-cash claims (`claim1.paid == 30000`, `claim2.paid == 20000`, `total_paid == 50000`) are robustly PRD-derivable and are fully asserted across the instance's 2 tests, so the instance remains covered.

## Step 6: Generate Implementation — 2026-06-19T00:00:00.000Z

All modules compile and the full implementation is in place. The implementation is complete and thoroughly verified.

## Summary

I generated a complete Python + Flask implementation for the Ambulance & EMS Billing API at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0406_ambulance_ems_billing/workspace/implementation/`.

### Structure
- `start.sh` — guarded-install foreground launcher (`exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000; skips `pip install` when Flask is already importable to avoid per-test-reboot contention)
- `app.py` — blueprint registration, global error handlers, and a `socket.getfqdn` shim to keep boot fast under per-test-server isolation
- `db.py` — in-memory store, fresh and empty on every boot (no seeding)
- `errors.py`, `response.py`, `middleware.py` — error catalogue, the exact `meta`/`response_type`/`data` envelope, and `X-User-ID`/`X-User-Role` auth with anonymous bootstrap-open support
- `services/` — `calc.py` (all §1.3 fee-schedule/adjudication/charity math with `Decimal` round-half-up), `ledger.py` (pinned 6-step reconciliation + automatic billing-dimension cascade), `transport.py` (PCS requirement + charge synthesis), `common.py`, `serialize.py`, `timeutil.py`
- `routes/` — all 44 endpoints across agencies/staff, payer-plans, patients, fleet, unit-assignments, transports, claims, remittances, payments, adjustments

### Key behaviors verified end-to-end (every assertion passed)
- **Charge calc**: BLS/ALS1/ALS2/SCT base codes, per-tier rural mileage bonus (first 17 miles ×1.5, round-per-tier-then-sum) — e.g. rural ALS2 20mi = 159875¢
- **Adjudication dual-variant**: payer-reported vs Medicare-baseline-derived (Medicaid ×0.80, commercial/auto ×QPA), with COB cap `min(allowed, billed − prior_paid)`
- **Contractual adjustment** by payer type + sequence rank; **patient-responsibility waterfall** flooring at 0
- **Three liability trajectories**: Medicare/Medicaid auto-writeoff cost-share; commercial standard balance-bill; No-Surprises `BALANCE_BILLING_CAP` writing the gap down to cost-share
- **Parallel state machines**: documentation lifecycle (incl. RETURNED↔NECESSITY_REVIEW loop) and billing lifecycle with automatic BILLING_IN_PROGRESS→BILLED→PATIENT_BALANCE/CLOSED advancement, including the "no further payer to bill" exhaustion rule (PRD §3.8)
- **CREATE-with-supersede + OCC**: primary rebill supersedes prior rank-1 claim; stale `expected_transport_version` → 412
- **Denial→appeal→resubmit** cycle; **charity FPL test** with whole-percent rounding; **unit-assignment overlap** (vehicle closed+buffer with boundary-touch conflict vs. crew half-open back-to-back allowed)
- Validation precedence (auth→authz→path→body-FK→shape→enum→business gates) and all 33 error IDs with correct HTTP statuses

The boot contract was confirmed via `bash start.sh` responding 200 on `0.0.0.0:$PORT`, and all 24 source modules compile cleanly.

## Step 7: Test-Diagnose-Fix Loop — 2026-06-19T00:00:00.000Z

Clean sweep confirmed. All 8 parallel rounds pass 68/68 with zero failures and consistent test counts.

## Summary

**Iterations run:** 2 (1 diagnostic baseline + 1 fix-and-verify sweep). Final sweep: all 8 parallel rounds 68/68.

The 6 failures were deterministic (same 6 in all 8 rounds — no flakiness), all rooted in test-side bugs, not implementation bugs. No tests were deleted; the implementation was already PRD-faithful.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_medicare_plan`: built the plan kwargs as a dict that overrides update, instead of passing `name=`/`allows_balance_billing=` positionally alongside `**overrides`. Previously `create_medicare_plan(org, name="...")` raised `TypeError: got multiple values for keyword argument 'name'`. (Fixed `test_active_payer_plan_claim_succeeds_after_deactivating_another`.)

**Fixes applied to `test_suite/` (STEP 2 — test made more faithful to PRD):**
- `test_03_claim_submission_and_sequence.py` — module-level helper `_setup_denied_primary_with_secondary_coverage` referenced `api` (a pytest fixture not in scope inside a plain function → `NameError`). Replaced the inline `api.create_remittance(...)` with the existing `post_remittance(org, ...)` helper (which uses the `api_client` singleton, as all other fixtures do) and added `post_remittance` to the import list. (Fixed `test_secondary_claim_matching_payer_accepted`, `test_secondary_claim_payer_mismatch_rejected`.)
- `test_04_adjudication_and_appeals.py` — same `NameError` in `_denied_primary`; switched to `post_remittance`. Additionally, the helper built a single-Medicare-coverage patient: per PRD §3.8 a settled DENIED claim with no further coverage at the next `policy_rank` auto-transitions to terminal `CLOSED` when the transport leaves `BILLING_IN_PROGRESS`, making the subsequent appeal impossible (PRD admits appeal only from `DENIED`). Added a rank-2 Medicaid coverage so the payer sequence is not yet exhausted, keeping the DENIED primary appealable — the precondition the denial-appeal-resubmit loop actually requires. (Fixed `test_claim_cycles_back_to_submitted_after_appeal_resubmit`, `test_resubmit_resets_allowed_and_paid_to_zero`.)
- `test_05_ledger_writeoffs_and_cascades.py` — `test_remittance_cascades_to_patient_balance` asserted the claim stays `PAID` after the cascade, but PRD §3.8 (verbatim) states "a settled claim whose status is `PAID` automatically transitions to the terminal `CLOSED`" when leaving `BILLING_IN_PROGRESS`. With a single Medicare coverage the sequence is exhausted, so the claim correctly becomes `CLOSED`. Corrected the assertion to `== "CLOSED"` and added the governing PRD §3.8 quote to the docstring — making the depth-3 cascade assertion faithful to PRD rather than contradicting it.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful (the `CLOSED` claim-status behavior the test had flagged is exactly what PRD §3.8 mandates).

## Step 8: Finalize PRD — 2026-06-19T00:00:00.000Z

`PRD_FINALIZED.md` was created (copy of `PRD.md`) and, after full analysis, **left byte-identical** — no edits were warranted.

**Line counts:** PRD.md = 291 lines; PRD_FINALIZED.md = 291 lines. **%-delta: 0%** (0 lines changed).

### Why no edits

Every Step 7 diff item is either a pure test-harness bug or a behavior the PRD already pins verbatim. Per the HARD SCOPE and "patch only when impl pinned a choice PRD left open / impl mismatches PRD" rules, none of the four items qualifies:

- **`create_medicare_plan` fixture bug** — Python kwargs collision (`TypeError`) in the fixture builder. Pure test-construction defect; the gated behavior (inactive-plan rejection) is fully determined by PRD §2.9/§3.6. No PRD silence.
- **`_setup_denied_primary_with_secondary_coverage` NameError** — module-level helper referenced a pytest fixture (`api`) out of scope. Pure test bug; the payer-sequence-match behavior is determined by PRD §3.6. No PRD silence.
- **`_denied_primary` NameError + added rank-2 Medicaid coverage** — the NameError is a pure test bug; the rank-2-coverage addition was forced by PRD §3.8 (verbatim): "a settled `DENIED` claim with no further coverage entry at the next `policy_rank` (one greater than its `sequence_rank`) likewise transitions to `CLOSED`." The impl's `close_settled_claims` (`(c["sequence_rank"] + 1) not in ranks_present`) implements exactly this. PRD already determines it.
- **`test_remittance_cascades_to_patient_balance` claim → CLOSED** — PRD §3.8 (verbatim): "a settled claim whose status is `PAID` automatically transitions to the terminal `CLOSED`." Step 7 corrected a wrong test assertion (PAID) to match PRD. PRD already determines it.

The Step 7 sweep reached 68/68 with **zero implementation changes**, confirming the implementation was already PRD-faithful.

### Per-edit pre-edit search log

No edits were committed, but the mandatory pre-edit enumeration was performed for the one candidate subject — the §3.8 auto-`CLOSED` / payer-sequence-exhaustion cascade that all four diff items revolve around:
- **(a) Subject:** the §3.8 cascade — claim settlement to `CLOSED`, payer-sequence exhaustion, and the appeal/resubmit precondition chain.
- **(b) Impl paths enumerated:** `services/ledger.py` (`sequence_exhausted`, `close_settled_claims`, `advance_billing_dimension`, `primary_claim`, `compute_patient_responsibility`, `reconcile_transport_ledger`); `routes/remittances.py` (cascade trigger); `routes/claims.py` (`appeal_claim`, `resubmit_claim`, submit/rebill); `routes/payments.py`, `routes/adjustments.py` (cascade triggers); `services/calc.py`; `routes/transports.py`. All consistent with PRD §3.8 prose as written.
- **(c) Wording adjustment:** none — every enumerated path is already correctly described by existing PRD §3.8/§3.6/§3.7/§3.9/§3.10 prose; editing would have risked a new false-universal claim (NO-NEW-MISMATCH rule).

## Step 9: Complete PRD — 2026-06-19T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Line/char counts:**
- `PRD_FINALIZED.md`: 291 lines, 50939 chars
- `PRD_COMPLETED.md`: 291 lines, 52421 chars (char-delta +1482; no line-count change — all edits are in-paragraph inserts)

**Counts:** ambiguity-pins: 3 — mismatch-revisions: 1

**Changes (one per edit):**
- §2.1 — revise — mismatch — Pinned that the three bootstrap-open creation endpoints (agency, payer plan, patient) enforce no role restriction: any valid role pair (or anonymous) is accepted; the §4 role lists for these three are advisory, only a malformed header pair yields `ERR_UNAUTHENTICATED`. Impl uses `optional_authenticate()` with no `require_role` — `routes/agencies.py:29`, `routes/payer_plans.py:25`, `routes/patients.py:23`, `middleware.py:43`.
- §3.6 — insert — ambiguity — Pinned that a downstream (secondary/tertiary) claim is admitted only while `billing_status` is `BILLING_IN_PROGRESS`, a fresh primary only while `UNBILLED` or `BILLING_IN_PROGRESS`, otherwise `ERR_INVALID_BILLING_STATE` (HTTP 409), and that this billing-state gate runs ahead of the documentation/necessity/PCS/payer-active/prior/sequence/version checks. Impl — `routes/claims.py:78-90` (and ordering through line 137).
- §3.7 — insert — ambiguity — Pinned that the payer `Payment` is created only when `paid_cents > 0`; a `PAID`/`PARTIAL` remittance with `paid_cents == 0` records no `Payment`. Impl — `routes/remittances.py:135`.
- §3.10 — insert — ambiguity — Pinned that every persisted `Adjustment` carries a `requested_amount_cents` field echoing the request verbatim (supplied value for discretionary types; null when omitted, including `CHARITY`/`BALANCE_BILLING_CAP`). Impl — `routes/adjustments.py:126`; confirmed by entity shape in `test_helpers/types.py:309-317`.

**Notable behaviors checked and left unchanged** (already uniquely pinned by PRD or consistent with it): fee-schedule/Medicare-baseline constants and per-tier rounding, the pinned six-step ledger reconciliation order, sequence-exhaustion and PAID/DENIED → CLOSED transitions, COB `prior_paid` summation, PCS-requirement test, charity FPL test, balance-billing-protection test, half-open crew vs. buffered-closed vehicle overlap semantics, and the FK-before-required-field validation ordering.

---

## Pipeline Complete — task_0406_ambulance_ems_billing

All steps 1–9 finished. Final state: 68 tests, all 8 parallel stability rounds at 68/68. Artifacts present: SCAFFOLD trio, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 6 files), implementation/ (Python+Flask, start.sh, 24 modules), results.{1..8}.json (all passing).

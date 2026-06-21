# Worklog — task_0412_drug_pricing_340b_compliance

Scenario: 340B Drug Pricing & Compliance (HRSA): covered-entity registration & child sites, eligible-patient determination, split-billing & accumulator, contract-pharmacy dispensing, duplicate-discount/Medicaid carve-out, GPO prohibition, audit & self-disclosure, ceiling-price reconciliation

Difficulty: Expert (passed only to Step 2 scaffold generator)

## Step 1: Create task directory — 2026-06-19T03:03:08.000Z

Created `tasks/task_0412_drug_pricing_340b_compliance/` with `workspace/` subdirectory. Confirmed `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-19T03:21:00.000Z

Scaffold-generator subagent ran (Expert difficulty target passed to this step only). The subagent's connection closed mid-summary, but all three artifacts were written and verified by the orchestrator:
- `SCAFFOLD.yaml` — 1700 lines, valid YAML. Counts: 13 entities, 5 state_machines, 7 calculations, 18 validations, 59 endpoints, 23 errors, 3 roles, 2 concurrency_rules. Top-level keys: scenario, domain_name (drug-pricing-340b-compliance), api_prefix (/340b), complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Neither scaffold_difficulty_design nor scaffold_corner_design key present (correct).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 987 lines, valid YAML, single top-level key `scaffold_difficulty_design` (list of 9 rule groups, 18 total instances).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1647 lines, valid YAML, single top-level key `scaffold_corner_design` (list of 9 sections, 50 total instances).

## Step 3: Copy INSTRUCTION.md — 2026-06-19T03:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0412_drug_pricing_340b_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-19T03:31:00.000Z

PRD generated at `workspace/PRD.md` — 312 lines. Sections: §1 Introduction, §2 Global Specifications (RBAC, §2.2 verbatim response envelope, pagination, common resource properties incl. prescriber common_fields:false exception, nested retrieval/referential integrity, validation order/precedence, optimistic concurrency on reconciliation writes, monetary/quantity precision, compliance posture as derived gate), §3 Business Logic (11 subsections: CE registration & adjudication, child sites/prescribers/patients, drug products & ceiling-price model, contract pharmacies half-open window overlap, dispense eligibility cascade 5 prongs, split-billing accumulator & replenishment, reverse/reinstate/disclose, audit findings & review lifecycle, repayment obligations & remittance, purchase orders/GPO prohibition/ceiling reconciliation, Medicaid claims/duplicate-discount guard), §4 Endpoint Definitions (59 endpoints), §5 Error Code Catalogue (23 errors). Hard Contracts all PASS: Contract 1 field-name coverage 73/73; Contract 2 rule coverage (OCC, state machines, calculation variants, validation→error pairings, cascades); Contract 3 §3 path purity 0 violations. §2.2 emitted byte-identically. Confirmed: withheld design files NOT read; PRD contains 0 references to scaffold_difficulty/scaffold_corner/test_recipe.

## Step 5: Generate unit tests — 2026-06-19T03:44:00.000Z

(verbatim subagent summary)

Generated complete test infrastructure for `task_0412_drug_pricing_340b_compliance`.

Test helpers (Stage 1) — 9 files in `test_helpers/`: types.py (16 status/role enums + 13 entity TypedDicts; Prescriber carries only id/created_at per common_fields:false; all others full id/created_at/updated_at/version), api_errors.py (23 ApiErrorId members + HTTP status map; ERR_INVALID_REQUEST→422, ERR_STALE_VERSION→412), api_client.py (59 endpoint methods under /340b), assertions.py (per-entity assertions + repayment balance & accumulator remainder invariant checkers), factories.py (input-field-only payload factories with unique natural-key gen for hrsa_id/ndc/npi), constants.py, test_users.py (3 roles opaque + make_compliance_officer_headers for segregation-of-duties), fixtures.py (5 tiers composite setup), __init__.py (barrel export).

Test suite (Stage 2) — 6 files, 79 test functions in `test_suite/` (+ conftest.py): test_01_registration_and_entities.py (15), test_02_eligibility_and_pricing.py (12), test_03_accumulator_and_replenishment.py (10), test_04_state_machines.py (15), test_05_audit_repayment_reconciliation.py (12), test_06_validations_and_rbac.py (15).

Design-instance coverage: Queue A (Difficulty) 18 instances → 16 translated (≥2 tests each, 32 tests), 2 skipped. Queue B (Corner) 50 instances = 47 non-stub + 3 stubs → all 47 non-stub translated (≥1 test each, 1:1 no gaps/broken pointers); 3 stubs not translated; all 3 difficulty cross-references resolve.

Skips (2 instances, both error-precedence/validation-priority): (1) state_vs_business_safety_reverse_outranks_gpo_irrelevant — asserts ERR_INVALID_STATE on Medicaid-claim against REVERSED dispense but PRD documents no state precondition on medicaid-claims endpoint (only duplicate-discount guard); no coverage, not uniquely derivable. (2) cross_entity_referential_vs_ce_not_active_mismatch_outranks — asserts ERR_CROSS_ENTITY_MISMATCH wins but PRD §3.5 lists CE-active precondition first ("in a fixed order") so faithful reader expects ERR_CE_NOT_ACTIVE; PRD prose points to opposite outcome, not uniquely derivable. Corner stub state_vs_safety_priority_conflict_excluded defers to first skipped instance — left as a gap.

Verification: all helper+suite files byte-compile; all 81 PRD quote-segments survive whitespace-normalized grep of PRD.md; every api.<method> resolves to one of 59 defined methods; every name imported from test_helpers exported; no skip/skipif/xfail; no scaffold-leakage terms; exactly 79 Design: tags for 79 tests.

## Step 6: Generate implementation — 2026-06-19T03:44:00.000Z

(verbatim subagent summary)

Built complete Python + Flask implementation in `workspace/implementation/`.

Source files (27): Foundation — app.py (entry, blueprint reg under /340b, error handlers), db.py (in-memory store + UUID/timestamp/version helpers), errors.py (23-entry catalog), response.py (success/list/error envelopes), middleware.py (auth+RBAC+serialization), validation.py (field-shape+pagination), filters.py (query-param filtering), lookup.py (FK existence→404), requirements.txt, start.sh. routes/ (9): covered_entities, people, drug_products, contract_pharmacies, accumulators, dispenses, audit_findings, repayments, purchase_orders. services/ (5): eligibility, pricing, accumulator, compliance, repayment.

Endpoints: 59 (method, path) pairs — matches PRD §4 exactly.

State machines: CoveredEntity (PENDING→ACTIVE/DENIED, ACTIVE↔RECERT_DUE, →TERMINATED cascade to ACTIVE contract pharmacies; recertify gated on GOOD compliance_posture). PrescriptionDispense (parallel dimensions: dispense_status DISPENSED↔REVERSED→DISCLOSED terminal; classification_status 340B/WAC set at creation by 5-prong eligibility cascade; 340B branch cascades into accumulator; reverse/reinstate conserves accrued_units). AuditFinding (OPEN→UNDER_REVIEW↔DISPUTED revision loop →RESOLVED/DISMISSED; segregation-of-duties on self-disclosure dispute; repayment-required gate on resolve). RepaymentObligation (OWED→PARTIALLY_PAID→SETTLED, OWED→WAIVED). ContractPharmacyArrangement (ACTIVE↔SUSPENDED →TERMINATED).

Calculations: integer cents (no floats). Ceiling price inclusive penny boundary (URA≥AMP→1¢ PENNY). Published-over-provisional effective-ceiling selection (latest by created_at, tie-broken by internal insertion sequence so ids never decide order). Eligibility cascade (5 fixed-order prongs). Accumulator crystallisation via integer floor division emitting B340B purchase orders. Overcharge reconciliation pinned as sum-of-per-PO-floored (100+0+40=140). Repayment assessment max(0,wac−ceiling)×assessed_units. Compliance posture & open_repayment_cents recomputed on every audit/repayment side effect, each recompute bumping CE version/updated_at. OCC on two version-guarded writes (expected_accumulator_version, expected_drug_product_version → ERR_STALE_VERSION 412). Validation precedence per PRD §2.6 (auth→role→existence→shape→business). Prescriber carries only id/created_at.

Confirmations: start.sh reads $PORT (default 10000 via app.py), binds 0.0.0.0, runs foreground via exec python3 app.py, guards pip install on import flask. Storage in-memory only (dicts keyed by id), zero entities at startup, no seeding. Verified clean boot + 80+ end-to-end assertions passing.

## Step 7: Run tests and iterate to green — 2026-06-19T03:50:00.000Z

(verbatim subagent summary)

All 8 parallel rounds pass with 79/79. Clean sweep confirmed.

Iterations run: 2 (baseline sweep showed a single deterministic failure across all 8 rounds; one fix; confirming sweep was clean across all 8 rounds, 79/79 each).

Tests deleted: None.

Fixes applied to test_suite/: test_05_audit_repayment_reconciliation.py — test_waive_after_partial_remit_zeroes_balance (renamed to test_waive_owed_obligation_zeroes_balance): the test remitted 5000 against a 12000 obligation (driving it to PARTIALLY_PAID) and then asserted that a waive on that PARTIALLY_PAID obligation returned 200. This contradicts the test's own cited PRD §3.9 sentence — "an HrsaAuditor may waive an OWED obligation" — which scopes waive to OWED status only. The PRD (and the canonical scaffold state machine, which defines only a from: OWED → to: WAIVED transition guarded by status == OWED) is silent on / contradicts a PARTIALLY_PAID → WAIVED transition, so a PRD-faithful implementer correctly rejects it with ERR_INVALID_STATE (HTTP 409). This was a STEP 2 test-vs-PRD consistency bug: the setup constructed a precondition (PARTIALLY_PAID) inconsistent with the PRD's waive precondition (OWED). Made the test MORE faithful by removing the prior partial remit and waiving an OWED obligation directly, while preserving the design instance's money-conservation-to-zero assertions (remaining_balance_cents == 0 and open_repayment_cents == 0), both uniquely PRD-derivable from §3.9 and the §2.9 posture gate.

Fixes applied to test_helpers/: None.

Fixes applied to implementation/: None — the implementation was already PRD-faithful (its OWED-only waive guard is exactly what the verbatim PRD prose requires).

Final state: 8/8 parallel rounds green, 79/79 tests passing each round, fully deterministic (no flakiness observed). Orchestrator independently verified all 8 results.*.json show 79/79.

## Step 8: Finalize PRD — 2026-06-19T03:51:00.000Z

Step 8 ran (Step 7 had 1 test_suite/ fix, so the zero-iterations skip condition was not met). Result: PRD_FINALIZED.md is byte-identical to PRD.md (312 lines, 0% delta; orchestrator-verified `diff` reports no difference).

(verbatim subagent summary)

PRD_FINALIZED.md is an exact copy of PRD.md (no edits) — the PRD already uniquely pins the waive precondition. The sole Step 7 item was a test_suite/ fixture fix with no implementation fix. Confirmed against implementation/: PRD §3.9 (PRD.md line 202) already states verbatim "an HrsaAuditor may waive an OWED obligation, moving it to the terminal WAIVED state with remaining_balance_cents set to 0", scoping waive to OWED-only. Implementation (routes/repayments.py:72-73) enforces exactly that (status != OWED → ERR_INVALID_STATE 409, then WAIVED + remaining_balance_cents=0). PRD uniquely determines the behavior, so no edits were invented. Pre-edit search log: subject = waive precondition on repayment obligations + adjacent status transitions; enumerated routes/repayments.py (waive/remit/list/get), services/repayment.py (assess_finding_repayment), services/compliance.py (recompute_ce_posture treats OWED/PARTIALLY_PAID as open), grepped tree for waive|WAIVED|OWED|PARTIALLY_PAID — no other off-site path waives/transitions repayment status; no wording change needed. (Note: subagent looked for test_suite/test_helpers under workspace/ where they are absent — they live at task root; harmless since tests are not the alignment target.)

## Step 9: Complete PRD — 2026-06-19T03:55:00.000Z

Full PRD-vs-implementation completeness scan. PRD_COMPLETED.md created from PRD_FINALIZED.md. Line count unchanged (312); char delta +2,518 (all in-paragraph). 8 edits: 6 ambiguity-pins, 2 mismatch-revisions.

(verbatim subagent summary)

Changes (one per edit):
- §2.9 Compliance Posture — revise — mismatch — PRD said every recompute mutates (refreshes updated_at/bumps version); impl only mutates when compliance_posture or open_repayment_cents actually changes, else no-op — services/compliance.py:31-38
- §3.2 Prescribers — insert — ambiguity — duplicate npi collision rejected with ERR_INVALID_REQUEST (422), no dedicated duplicate-NPI code — routes/covered_entities.py:233-235
- §3.3 Selecting the effective ceiling — insert — ambiguity — effective-ceiling read returns full serialized ceiling record plus effective_variant field (FINAL/PROVISIONAL); 404 when none; requires quarter query param (422 if absent/malformed) — routes/drug_products.py:137-154
- §3.5 Recording a Dispense (preconditions) — revise — mismatch — impl evaluates ERR_CROSS_ENTITY_MISMATCH before ERR_CE_NOT_ACTIVE, and contract-pharmacy-active check (ERR_INVALID_STATE) after CE-active; PRD prose ordered CE-active first — routes/dispenses.py:64-79
- §3.5 Recording a Dispense (CP not active) — insert — ambiguity — non-ACTIVE contract_pharmacy_id rejected with ERR_INVALID_STATE (409) — routes/dispenses.py:78-79
- §3.6 Manual replenishment — insert — ambiguity — emitted B340B PO priced from drug's most-recently-created ceiling record (published preferred), with that record's unit_price_paid_cents and quarter (falls back to 0/null when none); manual sweep leaves last_replenish_dispense_id unchanged — routes/accumulators.py:82-98, services/accumulator.py:35-53
- §3.9 Remitting / Waiving — insert — ambiguity — remit against SETTLED/WAIVED obligation rejected with ERR_INVALID_STATE (409) before amount-bounds check; waive against non-OWED obligation rejected with ERR_INVALID_STATE (409) — routes/repayments.py:46-50,72-73
- §3.10 Ceiling-price reconciliation — insert — ambiguity — ERR_STALE_VERSION checked before published-ceiling check; obligation source_ref_id = effective published ceiling record id, covered_entity_id from first chronological B340B PO; returns 201 with obligation, or 201 with empty {} when overcharge not > 0; version bumped in both cases — routes/drug_products.py:171-241

Tests used only as auxiliary cross-reference; no pinned behavior authority-derived from weakened test assertions.

## Pipeline complete

All 9 steps finished. Final state: 79/79 tests passing across all 8 parallel stability rounds (per-test-server isolation). Deliverables present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/, test_suite/ (79 tests), workspace/implementation/ (27 files, Flask, in-memory).

# Worklog — task_1070_property_tax_appeal

## Step 1: Create task directory — 2026-07-21T00:00:00.000Z

Directory pre-assigned and pre-existing: tasks/task_1070_property_tax_appeal/ with workspace/ subdir. No index scan performed (folder pre-assigned to avoid parallel ID contention). Difficulty = Expert.

## Step 2: Generate scaffold — 2026-07-21T11:36:00.000Z

All three scaffold artifacts are complete, parse cleanly, and pass `scaffold_lint.py` (VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5, all §1.1 FKs have reverse-reachability; 414 calls scanned).

## Summary — task_1070_property_tax_appeal (Expert)

Generated purely from the scenario + skill spec (no sibling tasks consulted). Domain: contingency property-tax appeal firm — workflow-orchestration primary archetype blended with pricing-engine, flat FK topology, branching+cyclic state machines, segregation-of-duties RBAC.

**SCAFFOLD.yaml counts**
- Entities: **13** (Analyst, Client, Jurisdiction, FeeAgreement, Parcel, Assessment, ExemptionClaim, Appeal, Evidence, Hearing, SettlementOffer, Invoice, Payment)
- Endpoints: **48** (incl. `/_clock/set_current_utc` defaulting to 2026-07-01T00:00:00Z; reverse-reachability GETs for all 14 FKs via sub-resource + filtered-list forms)
- Errors: **19**
- Roles: **4** (FirmAdmin/opaque, Analyst/entity_backed, Billing/opaque, Client/entity_backed)
- State machines: **7** (Appeal branching fork→{DECIDED,SETTLED,WITHDRAWN}; SettlementOffer cyclic PROPOSED↔COUNTERED; plus Assessment, ExemptionClaim, Hearing, Invoice, FeeAgreement)
- Calculations: **6** — dual-variant `opinion_of_value` (SALES_COMPARISON vs ASSESSMENT_EQUITY) and dual-variant `contingency_fee` (provisional vs final, marginal-tiered), plus `tax_savings`, `comp_adjusted_sale_value`, `assessment_projected_annual_tax`, `invoice_amount_paid`
- Concurrency rules: **1** (OCC on Appeal.version at settlement-offer create → ERR_STALE_APPEAL_VERSION 412; CREATE-with-supersede)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml**: all 9 Difficulty Rules × 2 = **18 instances**. All formula-derived asserts pre-computed as literals (valuation 30000000 vs 29000000; fee 28250/15000/36500; savings 75000/100000/25000; projected tax 750000/625000; per-comp-round-before-median 102).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml**: **28 instances** across all 9 claim-guide sections — **23 active** + **5 `excluded_because` stubs** (pointing to named §1.8 instances). Covers CRUD/404/required-field/computed-field, invalid-transition/idempotency/terminal-lockdown, calc floor/correctness, auth/authz/invalid-value/duplicate, FK reverse-list, wrong-owner, OCC stale-version 412 + version-increment, derived-field reconciliation, and immediate-consistency.

Key design choices worth noting for downstream stages: filing no longer requires an ACTIVE fee agreement (moved to invoice issue) so the referential/fiscal validation pair is reachable; the DECIDED/SETTLED cascade **always** creates a DRAFT Invoice (even at zero savings) so the zero-savings fiscal boundary is testable at issue; the multi-year re-appeal path (fresh appeal on a FINALIZED assessment) drives the Appeal→Assessment cross-entity dependency.

Post-Step-2 validation: all three files yaml.safe_load cleanly (no bare `?`/nested `[` fixes needed). Constant audit: no undeclared numeric constants — all pricing constants declared as FeeAgreement field defaults (tiers 0.40/0.33/0.25, ceilings 50000/150000, min 15000); jurisdiction params (filing_window_days, equalization_ratio, millage_rate) are per-row required fields supplied at creation; rep_travel_buffer_minutes default 60, hearing_room_capacity default 3. No pre-patching required.

## Step 3: Copy INSTRUCTION.md — 2026-07-21T11:37:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1070_property_tax_appeal/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-21T11:46:00.000Z

The PRD is complete and all three hard contracts pass. Final summary below.

## PRD generated: workspace/PRD.md

**Line count:** 272 lines.

**Section list:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Monetary & Ratio Precision, 2.6 Logical Clock, 2.7 OCC, 2.8 Cascading Consistency & Compensating Reversals, 2.9 Nested Retrieval & Referential Validation, 2.10 Order of Validation); §3 Business Logic (3.1 Firm Setup, 3.2 Parcels/Assessments/Exemption Ledger, 3.3 Comparable Evidence & Opinion of Value, 3.4 Filing the Appeal, 3.5 Hearings & Scheduling Constraints, 3.6 Settlement Negotiation, 3.7 Resolving the Appeal, 3.8 Billing); §4 Endpoint Definitions (48 endpoints); §5 Error Code Catalogue (19 errors).

**Coverage:** all 13 entities, 48 endpoints (incl. `/_clock/set_current_utc`), 19 errors, 7 state machines, 6 calculations, 1 OCC rule. Contracts 1/2/3 all PASS (0 missing fields, priority orderings surfaced, 0 §3 path leaks).

**Scaffold constants surfaced into prose:** filing-window inclusivity, equalization_ratio bounds (0<r≤1, 0.90 example), hearing_room_capacity default 3, rep_travel_buffer_minutes default 60 (exactly-buffer-apart allowed), contingency tiers 0.40/0.33/0.25, ceilings 50000/150000, minimum_fee_cents 15000, millage /1000 formula, taxable-base floor at 0, logical-clock default 2026-07-01T00:00:00Z.

**Judgment call:** scaffold's SETTLED cascade was internally asymmetric (HEARING_SCHEDULED→SETTLED gated invoice on realized_savings>0; other branches unconditional). PRD unified all terminal outcomes to always create the DRAFT invoice (fee 0 when savings not positive); zero-savings boundary enforced at issue via ERR_NO_BILLABLE_SAVINGS.

## Step 5: Generate unit tests — 2026-07-21T12:07:00.000Z

All files compile, no scaffold leakage. test_helpers/ (9 modules: types, api_client, api_errors, assertions, factories, constants, test_users w/ make_analyst_headers/make_client_headers, fixtures w/ setup_base/setup_filed_appeal/setup_decided_appeal/setup_issued_invoice, __init__). test_suite/ (8 files, 59 test functions, conftest.py): test_01 CRUD, test_02 access-control, test_03 state-transitions, test_04 valuation, test_05 fees/billing, test_06 appeal-resolution, test_07 settlement, test_08 hearings.

Coverage: Queue A (Difficulty) all 18 instances × 2 tests = 36 tests, no skips. Queue B (Corner) all 23 non-stub instances × 1 = 23 tests, no skips. 5 excluded_because stubs correctly not emitted. No orphan Design tags; every docstring ends with verbatim Design: line + PRD citation. pp_deadline/pp_sod priority-pairs legit (PRD §3.4/§3.6 state ordering in prose).

## Step 6: Generate implementation — 2026-07-21T12:07:00.000Z

Implementation complete and verified. Files: start.sh (foreground, guarded pip, exec python3 app.py, binds 0.0.0.0:$PORT default 10000), requirements.txt (flask==3.0.3), store.py (in-memory dicts + logical clock default 2026-07-01T00:00:00Z), calc.py (Decimal round-half-up, median, opinion-of-value both variants, tax_savings, tiered contingency_fee, projected tax), common.py (envelope, ApiError, auth, validators, pagination), domain.py (FK/ownership resolution, exemption reconciliation, terminal cascades), app.py (48 routes + error handlers).

Registered routes: 48 == scaffold §endpoints (48). PARTIAL-WRITE GUARD PASSED (48 rules / 48 method+path combos / 48 scaffold endpoints; app.py imports cleanly). Storage: in-memory dicts only, no seeding, boots empty.

PRD-silent behaviors resolved by concrete choice (Step 8/9 candidates): analyst ownership left unenforced (only Client ownership + settlement SoD explicit); existence-before-ownership (404-then-403) for FK-chain ownership, clients/{id} self-check pre-existence; missing-assessment on exemption APPROVE → ERR_INVALID_STATE 409; informal_review_available==false → ERR_INVALID_STATE 409; settlement invoice always created on SETTLED (fee 0 when savings≤0); settlement-offer create not gated on appeal state (only OCC); entity-creation constraint violations → ERR_INVALID_REQUEST 422, ERR_INVALID_VALUE reserved for priority-16 bounds; email uniqueness → ERR_DUPLICATE 409; ledger mutations bump client version.

## Step 7: Test/iterate fix loop — 2026-07-21T12:17:00.000Z

Clean first-sweep pass. All 8 rounds passed 59/59 with 0 failures and 0 errors (verified all 8 results.${i}.json). 2-waves-of-4 sweep via sweep.sh, no flakiness surfaced.

- Iterations run: 1 (clean first-sweep pass).
- Tests deleted: None.
- Fixes applied to test_helpers/: None.
- Fixes applied to test_suite/: None.
- Fixes applied to implementation/: None.
- Final sweep: all 8 rounds 59/59, 0 failed, 0 errors. Test count 59 across 8 files (test_01=9, test_02=6, test_03=3, test_04=4, test_05=10, test_06=16, test_07=7, test_08=4).

Matches the "clean first-sweep pass" pattern: residual PRD silences (the impl-gen flagged choices) were not exercised as test failures → Step 9 audit material.

## Step 8: Finalize PRD — SKIPPED — 2026-07-21T12:17:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the sites Step 7 touched. No PRD_FINALIZED.md produced. Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-07-21T12:28:00.000Z

All edits applied as in-paragraph inserts/revisions (line count unchanged at 272; +2,655 chars → 46,998). Full impl walk (app.py, calc.py, common.py, domain.py, store.py) against PRD.

- Source PRD.md 272L/44,343 chars → PRD_COMPLETED.md 272L/46,998 chars (+2,655).
- Counts: 11 ambiguity-pins, 5 mismatch-revisions (16 discrete changes / 13 edits).

Changes:
- §2.1 (analyst) — revise — mismatch — no analyst FK ownership gate; only settlement-offer SoD (app.py SoD ~820).
- §2.1 (client/ownership) — revise — mismatch — ERR_FORBIDDEN_NOT_OWNER only on Client GETs; existence(404) precedes ownership(403) for FK-chain, except client self-fetch (403 before 404).
- §2.10 — revise — mismatch — precedence aligned: existence before ownership for FK-chain, client self-fetch excepted.
- §3.1 (analyst) — email uniqueness → ERR_DUPLICATE; active recorded not enforced.
- §3.1 (client) — email uniqueness → ERR_DUPLICATE; portal_enabled recorded not enforced at auth.
- §3.1 (jurisdiction) — filing_window_days<1 / equalization_ratio ∉ (0,1] → ERR_INVALID_REQUEST.
- §3.2 (assessment) — negative assessed / non-positive millage → ERR_INVALID_REQUEST.
- §3.2 (exemption) — negative exemption_value → ERR_INVALID_REQUEST.
- §3.2 (exemption decide) — APPROVE w/ no matching assessment → ERR_INVALID_STATE 409.
- §3.3 (evidence) — negative sale_price/comp_assessed → ERR_INVALID_REQUEST.
- §3.5 (informal review) — jurisdiction w/o informal review → ERR_INVALID_STATE 409.
- §3.6 (offer create) — negative offer_value → ERR_INVALID_VALUE; create NOT gated on appeal live-state (only OCC + value bound); live-state gate only on counter/accept.
- §3.6 (counter) — requires offer_value≥0 but value ignored when re-proposing COUNTERED.
- §3.8 (payment) — non-positive amount → ERR_INVALID_VALUE.
- §3.8 (ledger) — issue/void/payment bump client version/updated_at.

Verified already-pinned (no change): dual-variant valuation per-comp-round-before-median; tiered fee sum-then-round-once + min-fee floor only when savings>0; tax_savings provisional/final; projected-annual-tax floor at 0; projected_client_tax_bill unfloored; OCC expected_appeal_version → ERR_STALE_APPEAL_VERSION 412; settlement invoice always created on SETTLED/DECIDED (fee 0 when savings≤0); withdraw/void/issue compensating reversals.

## Pipeline complete — 2026-07-21T12:28:30.000Z

DONE. workspace/PRD_COMPLETED.md exists; final 8-round sweep all-green (8 rounds × 59/59, 0 failed). PRD_FINALIZED.md correctly absent (Step 8 skipped). Route-count 48 == scaffold endpoints 48. Clean first-sweep Expert pass.

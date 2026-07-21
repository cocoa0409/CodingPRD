# Worklog — task_1052_public_adjuster

## Step 1: Create task directory — 2026-07-18

Created `tasks/task_1052_public_adjuster/` and `tasks/task_1052_public_adjuster/workspace/` via mkdir. Pre-assigned path used verbatim (no index scan).

## Step 2: Generate scaffold — 2026-07-18T03:55:00.000Z

All three artifacts complete and pass validation. scaffold_lint.py reports VERDICT: clean lint (516 calls across §1.8+§1.9 conform to §1.5; all FKs reverse-reachable).

Scale:
- 11 entities: Adjuster, License, Client, Policy, Contract, Claim, Supplement, Appraisal, Payment, Disbursement, Dispute (flat topology, FK-linked; 12 FKs each with a reverse-reachability GET)
- 60 endpoints (11 single-GET, 9 filtered-list GET, plus creates/actions, and a /v1/_clock/set_current_utc test-driving endpoint defaulting to 2026-07-01T00:00:00Z)
- 25 errors (all triggerable — verified)
- 5 roles: PublicAdjuster (entity_backed:Adjuster), FirmPrincipal (opaque), Client (entity_backed:Client), Carrier (opaque), System — role_model = segregation_of_duties
- 9 state machines: Claim (cyclic negotiation), Appraisal (branching fork-join agree/umpire), Contract (rescission + revert), License, Policy, Supplement, Payment, Disbursement (hold/resume cycle), Dispute
- 6 calculations (dual-variant fee provisional/final; dual-variant policy exposure forward/booked; disbursement waterfall; per-payment fee rounding; statutory fee cap; ACV depreciation)
- 1 concurrency rule: OCC on Claim.version at supplement create (ERR_STALE_CLAIM_VERSION, 412)

Design coverage:
- §1.8 difficulty design: 18 instances — exactly 2 per each of the 9 difficulty rules
- §1.9 corner design: 31 active instances + 5 excluded_because stubs (36 corner names; 54 unique names total across both files)

Notes/decisions:
- Primary archetype multi-party negotiation + secondary ledger reconciliation; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.
- Rule 8 (temporal overlap): closed-inclusive License validity intervals per (adjuster, state) vs half-open inspection windows with a 60-min travel buffer on the adjuster's calendar.
- Rule 9 (compensating invariants): cash cents (recovery = fee + advance-recoup + client) and coverage-limit capacity (limit = remaining + committed).
- Made rescission reachable from ACTIVE; added Claim.settled_at anchoring supplement window; added SETTLED/IN_APPRAISAL→WITHDRAWN cascades; removed unreachable ERR_NO_OFFER_TO_APPRAISE; pruned 3 dead enum values for enum closure.
- All formula-derived assertions computed in code and pinned as literals.
- Did not consult any sibling task directory.

## Step 3: Copy INSTRUCTION.md — 2026-07-18T03:56:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1052_public_adjuster/workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-07-18T04:02:00.000Z

Generated workspace/PRD.md (287 lines) from SCAFFOLD.yaml. 5 top-level sections (Intro; Global Specs w/ 11 subsections incl. RBAC/envelope/pagination/monetary/cascades/OCC/licensing-exposure-SoD/validation-ordering/logical-clock; Business Logic w/ 8 lifecycle subsections; Endpoint Definitions; Error Catalogue). 60/60 endpoints documented, 24/24 errors documented. Hard contracts all PASS (field-name coverage 71/71, rule coverage all 9 SMs + dual-variant fee/exposure + waterfall + cap + OCC, §3 path purity 0 violations). Did NOT read design files.

Flagged 3 undeclared named window/buffer constants (RESCISSION_WINDOW_DAYS, SUPPLEMENT_WINDOW_DAYS, TRAVEL_BUFFER_MINUTES) — projected by name w/o inventing figures.

## Step 4.5: Pre-Step-5 constant patch — 2026-07-18T04:03:00.000Z

Recovered concrete values from design files' worked examples and pinned them into BOTH SCAFFOLD.yaml and PRD.md (per "named window/buffer constants" memory pattern):
- RESCISSION_WINDOW_DAYS = 3 (corner: signed 2026-07-01 → deadline 2026-07-04; difficulty line 279 confirms).
- SUPPLEMENT_WINDOW_DAYS = 365 (corner: settled 2026-07-01, submit 2027-07-02 = 366d > 365 → ERR_SUPPLEMENT_WINDOW_CLOSED).
- TRAVEL_BUFFER_MINUTES = 60 (difficulty line 514: half-open windows with 60-min gap).
SCAFFOLD re-validated via yaml.safe_load OK. PRD prose pins each value inline ("equals 3 days", "equals 365 days", "equals 60 minutes"). Both files parse; done before Step 5/6 launch so the values are uniquely derivable for test-gen and impl-gen.

## Step 5: Generate unit tests — 2026-07-18T04:18:00.000Z

test_helpers/ (8 files + __init__.py): types.py (11 entity TypedDicts), api_client.py (42 endpoint methods), api_errors.py (24 errors), assertions.py (per-entity + policy/waterfall invariants), factories.py, constants.py (RESCISSION=3, SUPPLEMENT=365, TRAVEL_BUFFER=60), test_users.py (entity-backed PublicAdjuster→Adjuster.id, Client→Client.id; opaque FirmPrincipal/Carrier/System), fixtures.py.
test_suite/: conftest.py + 9 domain test files.
Counts: 9 test files, 67 total tests. Queue A (Difficulty) = 36 (18 instances × 2). Queue B (Corner) = 31 (31 non-stub × 1). Skipped instances: NONE — every difficulty + non-stub corner instance passed the PRD-first two-condition filter (windows now have concrete constants → uniquely derivable). 5 excluded_because validation stubs correctly not translated. payment_reverse_after_release_blocked_stub translated (full test_recipe, asserts ERR_DISBURSEMENT_RELEASED, PRD §3.7 covers). Verification: all imports OK, every PRD citation verbatim-present (0 mismatches), every api.<method> resolves, 0 coverage shortfalls, pytest collects 67 with no errors.

## Step 6: Generate implementation — 2026-07-18T04:18:00.000Z

workspace/implementation/ (7 files): start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground, guarded pip install, exec python3 app.py), app.py (Flask factory, envelope error handlers), store.py (in-memory dicts, monotonic seq, logical clock default 2026-07-01T00:00:00Z), common.py (envelope, auth, error catalogue, ROUND_HALF_UP, validators, pagination, version/updated_at), domain.py (dual policy exposure, provisional/final fee, waterfall, license validity, rescind cascade), routes.py (all 60 endpoints), requirements.txt (Flask 3.0.3). Endpoint count: 60 matching PRD §4. ast.parse OK on all 5 .py; start.sh exists. Live smoke tests confirmed full negotiate→settle→pay→disburse→release chain, cascades, SoD, OCC, rescind cascade, appraisal umpire, inspection overlap boundary.
Key spec-fidelity decisions (for later pinning): (1) claim-file precondition order follows §3.3 endpoint narrative (contract-active→policy-active→license→loss-period) over generic §2.10 order — PRD sources conflict. (2) Policy committed_cents = Σ(SETTLED settlement_amount) + Σ(PAID amount_recovered); approved-supplement amounts folded into claim settlement_amount to avoid double-count. (3) Payment reverse does not modify advance_recouped_cents (recoup applied only at release; restore clause is no-op). (4) Ownership enforced only for entity-backed Client on contract sign/rescind. (5) All timestamps from logical clock; user dates echoed verbatim.

## Step 7: Run tests and iterate — 2026-07-18T04:30:00.000Z

All 8 rounds pass 67/67. Clean sweep (near-clean pipeline).
Iterations run: 2 (baseline sweep + 1 fix sweep).
Tests deleted: NONE (no PRD-silence or non-derivability found).
Fixes to implementation/: NONE (implementation correct).
Fixes to test_suite/ (STEP 2 — fixture assertion boundary):
- test_07_disbursement_disputes.py, test_disbursement_release_blocked_by_open_dispute setup — added expected_status=201 to validate_success(api.create_dispute(...)).
- test_07_disbursement_disputes.py, test_disbursement_release_blocked_by_under_review_dispute setup — same fix.
Diagnosis: both failed deterministically across all 8 baseline rounds ("Expected 200, got 201" on the dispute-CREATE setup step, not the release assertion). PRD §4 line 194 states creates return 201 and line 252 lists POST /v1/disputes as a create → impl correctly returns 201; the two fixtures used default validate_success (expects 200) while every other create passes expected_status=201. Fix makes fixtures more faithful to PRD; no PRD-required check weakened.
Final: 67/67 passing in all 8 rounds. Ran sweep via workspace/sweep.sh as 2 waves of 4 (no inline pkill).

## Step 8: Finalize PRD — 2026-07-18T04:36:00.000Z

PRD_FINALIZED.md created as byte-for-byte copy of PRD.md — 0 edits. PRD.md = 286 lines, PRD_FINALIZED.md = 286 lines, 0% delta. Both <step_7_diff> items were pure test-fixture corrections (dispute-CREATE setup used default validate_success/200 but POST /v1/disputes correctly returns 201 per PRD §4 line 194 create rule). No implementation change, no deletion, no PRD-behavior change → no PRD silence or mismatch to pin. Byte-for-byte copy is the correct outcome (task_1039-style test-only-fix case). Step 8 NOT skipped by letter (2 test_suite fixes ≠ 0) but produced 0 edits as expected.

## Step 9: Complete PRD — 2026-07-18T04:42:00.000Z

PRD_COMPLETED.md produced as minimal patch over PRD_FINALIZED.md. 286 → 286 lines (all in-paragraph), char delta 43,105 → 44,024 (+919). 6 changed lines: 5 mismatch-revisions + 1 ambiguity-pin.
Changes (all confirmed against implementation/):
- §2.9 Policy exposure — revise — mismatch — committed_cents = Σ settlement_amount_cents (SETTLED) + Σ amount_recovered_cents (PAID, reconciled to actual recovery); approved-supplement amounts folded into claim settlement_amount_cents, not a separate term. domain.py:34-44.
- §2.10 Validation ordering — revise — mismatch — swapped priorities (5)/(6) so referential status (contract/policy active) precedes licensing validity, matching §3.3 narrative impl enforces. routes.py:515-522.
- §3.7 Payments/reverse — revise — mismatch — reversal leaves advance_recouped_cents unchanged (recoup only at release, reverse only pre-release → restore clause is no-op). routes.py:961-991.
- §2.1 RBAC PublicAdjuster — revise — mismatch — clarified no PublicAdjuster op acts on a resource with a direct adjuster FK, so adjuster-ownership comparison never triggers.
- §2.1 RBAC Client — revise — mismatch — extended "only the named client may sign" to also cover rescind (impl enforces client ownership on rescind). routes.py:403-404.
- §3.1 Onboarding policy — insert — ambiguity — pinned lapse/cancel act only from ACTIVE else ERR_INVALID_STATE. routes.py:281-289.
All other impl behaviors (state machines, fee/ACV/disbursement formulas, OCC, cascades, appraisal forks, dispute/hold-resume, pagination, envelopes, logical clock) already pinned uniquely by PRD.

## Pipeline complete — 2026-07-18T04:42:00.000Z

All Steps 2–9 done. Final sweep: all 8 rounds 67/67. Artifacts: SCAFFOLD*.yaml (3), workspace/PRD.md, PRD_FINALIZED.md (0-edit copy), PRD_COMPLETED.md (6 edits), test_helpers/ (9), test_suite/ (9 + conftest), workspace/implementation/ (7 files), results.{1..8}.json all passing.

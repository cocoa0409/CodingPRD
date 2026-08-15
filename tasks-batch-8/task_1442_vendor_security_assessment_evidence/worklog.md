# Worklog — task_1442_vendor_security_assessment_evidence

## Step 1: Create Task Directory — 2026-08-13T07:30:18.384Z

Task directory `tasks/task_1442_vendor_security_assessment_evidence/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE; no index scan performed, no other task_* directory touched. Difficulty directive from user: "harder than expert level" — Step 2 subagent instructed to target the Expert band's upper edge with maximum difficulty density per scaffold-generator §0.4.

## Step 2: Generate Scaffold — 2026-08-13T08:14:23.541Z

All three artifacts are written and lint-clean. Final summary:

## Summary

Generated the scaffold for `task_1442_vendor_security_assessment_evidence` purely from the scenario description plus the skill spec (no sibling tasks consulted).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile:** primary archetype `compliance_audit` + secondary `posture_driven_gating`; layers: cascading side effects, dual-variant calculation, version-pinning on approval, scheduled/deferred actions, optimistic concurrency; hybrid topology, cyclic state-machine shape, segregation-of-duties role model, immediate consistency.

**Counts:**
- Entities: 15 (Vendor, AssessmentTierPolicy, QuestionnaireTemplate, AssessmentCycle, QuestionnaireResponse, EvidenceArtifact, ExceptionFinding, RemediationPlan, RiskAcceptance, ContractAddendum, MonitoringAlert, SubprocessorDisclosure, OffboardingAttestation, ReassessmentSchedule, VendorContact)
- Endpoints: 72 (includes lint-mandated FK reverse-reachability GETs; deliberately above the §0.4 guideline midpoint per the harder-than-expert directive — every endpoint is exercised by a test recipe or structurally required)
- Error codes: 28
- Calculations: 8 (tier_assignment, questionnaire_response_score, evidence_review_score, composite_cycle_score, vendor_risk_score, addendum_requirement, tier_response_window, escalation_pull_forward) — 3 with explicit variants
- Cross-cutting gates: OCC on Vendor.version (cycle create) and AssessmentCycle.version (acceptance approve); segregation-of-duties on 4 gated pairs; posture gating; aggregate open-items gate on cycle approval; clock-swept auto-transitions (cycle EXPIRED, acceptance EXPIRED)
- State machines: 12 entities with 63 transitions total; cycles include questionnaire revision loop, remediation verify-reject compensation, template revise loop, acceptance expiry re-open loop

**§1.8 instances (19 total, ≥2 per rule):** dual_variant_calc ×3 (questionnaire provisional/final, evidence standard/strict window, vendor risk posture base), combinatorial_formula ×2 (modes a and b), non_linear_state_machine ×2, transitive_cascade ×2 (depth-3 acceptance-expiry chain, depth-2 alert-escalation chain), priority_pair_validation_conflict ×2 (state-vs-SoD, referential-vs-fiscal), boundary_precision_check ×2 (response deadline <=, coverage gap >180), cross_entity_state_dependency ×2 (cycle→addendum, subprocessor→vendor posture), resource_temporal_overlap ×2 (backward coverage-gap vs forward expiry-window semantics), compensating_invariant ×2 (open_exception_count conservation, reassessment-due monotonicity). All numeric asserts pre-computed in Python (e.g., 57.0, 67.5, 63.3, 85.21, 70.0, 68.0, 80.0, 97.0).

**§1.9 instances (41 total: 39 active + 2 excluded_because stubs)** across all 9 guide sections: entities 8, state_machines 7, calculations 4, validations 9, endpoints 3, errors 4, rbac 3, cross_cutting_layers 2, consistency_model 1.

**Lint:** `scaffold_lint.py` verdict block:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(688 calls scanned across §1.8+§1.9; 0 violations; required two §1.5 reshape iterations during generation — adding flat `/vsa/cycles/{id}/...` reverse-reachability GETs and a `/vsa/exceptions` filtered list — per the priority ladder.)

**Notable design decisions baked in:** clock default fixed at 2026-08-01T00:00:00Z; score fail-branch keeps cycle in RESPONSE_RECEIVED (avoiding a SCORED-with-RETURNED deadlock found during replay); offboard allowed from ONBOARDING to keep attestation chains reachable; OFFBOARDING_SLIP schedule kind wired to attestation-reject for enum closure; OCC errors split into ERR_STALE_VENDOR_VERSION / ERR_STALE_CYCLE_VERSION with ERR_STALE_VERSION as documented fallback.

## Step 3: Copy Shared Files — 2026-08-13T08:15:09.194Z

Copied `./INSTRUCTION.md` → `tasks/task_1442_vendor_security_assessment_evidence/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T08:43:38.386Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/workspace/PRD.md`.

## Summary

**PRD line count:** 348 lines.

**Section list:**
- §1 Introduction (2 paragraphs — business context + scope/clock determinism)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim block, byte-identical match verified) · 2.3 Pagination · 2.4 Common Resource Properties and Audit Fields · 2.5 Nested Resource Retrieval · 2.6 The Logical Clock and Scheduled State Transitions · 2.7 Optimistic Concurrency Control · 2.8 Segregation of Duties · 2.9 Validation Order and Error Precedence (23-tier cascade in prose) · 2.10 Numeric Precision, Scores, and Date Arithmetic · 2.11 Hierarchical Consistency and Version Cascades
- §3 Business Logic (9 subsections, lifecycle-timeline grouping): 3.1 Vendor Registration/Tier Policy/Risk Baseline · 3.2 Questionnaire Templates · 3.3 Cycle Creation/Issuance/Response Window · 3.4 Responses/Revision Loops/Scoring · 3.5 Evidence Artifacts/Review · 3.6 Exceptions/Remediation/Risk Acceptances · 3.7 Cycle Verdicts/Composite Score/Contract Addenda · 3.8 Monitoring/Escalation/Reassessment Cadence · 3.9 Subprocessors/Offboarding
- §4 Endpoint Definitions — 72 rows, 4 columns only (Method, Path, Description, Authorized Roles)
- §5 Error Code Catalogue — 28 rows, 2 columns only

**Zero-Silence Rule coverage audit (scaffold → PRD):**
- **§1.1 Entities (15):** all 77 unique field names appear as exact backticked tokens (strict script check: 0 missing); `common_fields: false` entities (`ReassessmentSchedule`, `VendorContact`) explicitly called out in §2.4 as carrying only `id` and `created_at` (no `updated_at`, no `version`).
- **§1.2 State machines (12):** every transition expressed with from/to state pairs (e.g., `RECEIVED → UNDER_REVIEW`), preconditions paired with their error IDs in adjacent prose, all side effects stated (version bumps, cascades into `open_exception_count`/`posture`/schedule journal entries). All 84 enum/state values verified present. Sibling-branch symmetry held: fail-vs-pass scoring branches (3.4), three evidence-review completion branches (3.5), verify-pass vs verify-reject plan outcomes (3.6), four offboard source postures (3.9).
- **§1.2.1 Concurrency rules (2):** both OCC guards fully specified in §2.7 and restated at point of use (§3.3 `expected_vendor_version`/`ERR_STALE_VENDOR_VERSION` 412; §3.6 `expected_cycle_version`/`ERR_STALE_CYCLE_VERSION` 412), framed in stale-version terms only; `ERR_STALE_VERSION` 422 noted as the reserved generic fallback; "endpoints not listed take no version field" stated.
- **§1.3 Calculations (8):** all formulas rendered as precise prose, no operator syntax (script-verified: no `>=`, `==`, `min(`, etc., no fuzzy words): tier_assignment matrix-override + rank-sum fallback with cutoffs 7/5/3 (§3.1); questionnaire score with NA-exclusion, half-up 2dp, 5%-per-revision penalty capped at 20, provisional-vs-final variants (§3.4); evidence score with per-kind bases 100/95/80/70/50, 365-day vs 180-day tier-dependent gap windows, severity deductions 25/15/8/3, floor at zero (§3.5); composite 40/60 weighting and pass thresholds 60/70/80/90 (§3.7); vendor risk score bases 50/60/20/45/85/70/10 with +5/+10 alert, +3 accepted-exception, +8 imminent-expiry modifiers, clamped 0–100 (§3.8); addendum clause sets (§3.7); response windows 45/30/21/14 (§3.3); pull-forwards 14/30/30 never-later (§3.8).
- **§1.4 Validations (24 rules, priorities 1–23):** full relative ordering expressed in §2.9 as a numbered precedence cascade (including the two priority-8 rules sharing a tier); every rule's trigger condition also restated near its workflow in §3. All 28 error IDs appear in §2/§3 prose (script-verified).
- **§1.5 Endpoints (72):** all present in §4 table (script-verified); all 58 unique request-body identifiers and all 11 query-param names covered in narrative (strict token check: 0 missing). Side effects (alert ingestion risk refresh, contact primary demotion, policy deactivation, revise-copy semantics, offboard compensation loop with +30-day slip and `OFFBOARDING_SLIP` journal) all expressed.
- **§1.7 RBAC (4 roles):** exact spellings, identity translation per role — `PlatformAdmin`/`RiskAnalyst`/`SecurityApprover` as opaque, `VendorContact` as entity-backed with vendor-scoped reads derived from the contact's `vendor_id` (§2.1).

**Hard-contract reports:** Contract 1 PASS (77/77 entity fields, 58/58 endpoint inputs, 11/11 query params). Contract 2 PASS (per the audit above; every validations priority, transition, calculation, OCC rule, side effect, and structured field default expressed). Contract 3 PASS (573 §3 backtick tokens scanned: 0 path tokens, 0 bare-method tokens, 0 method+path tokens).

**Scaffold rules requiring interpretation/adjudication:**
1. **`raw_score` description conflict** — the field description says "before na-adjustment" but the `questionnaire_response_score` formula excludes NA items from both sums before producing `raw`. I followed the formula (raw = post-NA-exclusion, pre-revision-penalty), since the formula and the scoring side effects are self-consistent.
2. **`acceptance_required` definition** — the entity field says "any HIGH/CRITICAL exception closed via RiskAcceptance" while the `composite_cycle_score` formula says "exists exception CLOSED_ACCEPTED" and the approval transitions set it unconditionally on any acceptance. I used the broader CLOSED_ACCEPTED-based reading, consistent with the formula and transition side effects.
3. **`ERR_STALE_VERSION` HTTP status** — validation row priority 6 says 412 for the entry, but the §1.6 catalog pins `ERR_STALE_VERSION` to 422. I treated the catalog as authoritative per-error (422) and kept the two specific OCC errors at 412.
4. **Overdue response submission** — the cycle transition says expiry "auto-fires first," yet validation 7 maps `ERR_DEADLINE_PASSED` to the submit endpoint. I wrote both orderings consistently with the validation priorities: overdue submission against a still-`ISSUED` cycle → `ERR_DEADLINE_PASSED`; once the sweep has moved the cycle to `EXPIRED` → `ERR_INVALID_STATE` (state check precedes deadline check).
5. **`ERR_SCORE_BELOW_THRESHOLD` vs the scoring fail branch** — the score endpoint's below-threshold outcome is a normal RETURNED transition, not an error; I scoped the error to "where the endpoint demands a pass" (the clean-approval path of evidence-review completion) while noting the score endpoint expresses failure as the revision branch.
6. **SUSPENDED → OFFBOARDING asymmetry** — scaffold deliberately omits the "no active cycle" precondition for the SUSPENDED branch (present for ONBOARDING/APPROVED/CONDITIONAL); I preserved that asymmetry verbatim in §3.9.

## Step 5: Generate Unit Tests — 2026-08-13T09:36:18.669Z

Done. Summary of what was generated for `task_1442_vendor_security_assessment_evidence`:

## Files written

**test_helpers/ (9 files):** `types.py` (4 role + 16 status/kind enums, 16 entity TypedDicts — append-only `ReassessmentSchedule`/`VendorContact` correctly omit `version`/`updated_at` per PRD §2.4), `api_client.py` (72 methods, one per PRD §4 endpoint), `api_errors.py` (28 error IDs + HTTP map, registered with the framework), `assertions.py` (per-entity structural asserts + `parse_instant`/`assert_instant_equal`/`assert_score` so datetime assertions compare instants, not serialization format), `constants.py` (all PRD thresholds: windows, pass scores, penalties, bases, pull-forward deltas), `test_users.py` (shared headers + per-instance builders incl. entity-backed `make_vendor_contact_headers(contact_id)`), `factories.py`, `fixtures.py` (composite chains: issued → scored → evidence-review → remediation → approved cycles, RISK_ACCEPTANCE_REVIEW setup, completed plans with distinct SoD analyst identities, offboarding, disclosures, alert helpers), `__init__.py` barrel.

**test_suite/ (10 files):** conftest + 9 numbered test files, 76 test functions (78 collected cases after pagination parametrization). Verified importable via `pytest --collect-only`.

## Coverage

- **Queue A (Difficulty): 19/19 instances, exactly 2 tests each (38 tests).**
- **Queue B (Corner): 38 tests covering all 39 non-stub instances except 1 skip; both `excluded_because` stubs left untranslated with cross-references verified resolvable.**
- Tag audit: every test carries exactly one `Design:` line; no dangling tags; all 110 docstring PRD citations survive a whitespace-normalized literal grep of PRD.md.

## Instances skipped / PRD-corrected (gaps kept as gaps)

1. **SKIP `Corner/calculations/tier_assignment_matrix_overrides_rank_fallback`** — PRD §3.1 says `tier_matrix` maps "classification triples to tiers" but never specifies the key serialization (the instance's `"PUBLIC|NONE|LOW"` format is not derivable); two PRD-only readers could ship different key formats. Not uniquely derivable.
2. **PRD-corrected `Corner/validations/response_submit_after_deadline_returns_deadline_passed`** — the instance asserts `ERR_DEADLINE_PASSED`, but per PRD §2.6 the clock-advance fires the expiry sweep synchronously and §3.4 states an already-`EXPIRED` cycle rejects submission "at the earlier state check with `ERR_INVALID_STATE` (HTTP 409)". The test asserts the PRD outcome (ERR_INVALID_STATE + cycle EXPIRED); the instance's `ERR_DEADLINE_PASSED`-on-submit path is unreachable under PRD semantics.
3. **PRD-corrected `Difficulty/cross_entity_state_dependency/cycle_approval_gated_by_addendum_state`** — the instance asserts `ERR_OPEN_ITEMS_OUTSTANDING`, but PRD §3.7 says "an outstanding addendum specifically with `ERR_ADDENDUM_OUTSTANDING`"; the test asserts ERR_ADDENDUM_OUTSTANDING.
4. **Dropped sub-assertions within otherwise-covered instances** (noted, not separately tagged): `version == 1` on create (PRD §2.4 never pins the counter's initial value — asserted `!= 99` for the ignored-input claim instead); `risk_score == 68.0` in `risk_acceptance_expiry_window_vs_clock` (PRD §3.8's refresh-trigger list omits acceptance *approval*, so the value at that instant is not uniquely derivable); `next_reassessment_due == 2026-09-10` in the acceptance-expiry cascade (null-existing-date min-semantics ambiguous) — the schedule-row kind/`reason_ref` assertions are retained; the halved-cadence exact date for CONDITIONAL approval (month-halving vs day-halving ambiguity) — posture CONDITIONAL is asserted instead.

Also note: two upstream recipes had broken setups that I repaired while preserving the asserted claim — `referential_before_score_threshold_on_acceptance_create` (all-NO answers can never pass scoring, blocking evidence upload; switched C1 to YES answers) and the plan-verify recipes (accept and verify used the same analyst identity, which would trip SoD first; verify uses a distinct analyst).

## Step 6: Generate Implementation — 2026-08-13T09:36:18.669Z

Implementation complete and verified. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded `pip install` (no-op once Flask present) + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 64 | App factory, blueprint registration, envelope-shaped 404/405/500 handlers, `0.0.0.0:$PORT` foreground run |
| `db.py` | 36 | In-memory stores (dicts keyed by id) + logical clock at `2026-08-01T00:00:00Z`; zero seeding |
| `errors.py` | 43 | `ApiError` + full error-id catalog |
| `response.py` | 50 | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit/offset/total_count/has_more` |
| `middleware.py` | 113 | `X-User-ID`/`X-User-Role` auth (401/403), VendorContact vendor-scoping, pagination bounds (422 last) |
| `helpers.py` | 151 | Left-to-right path resolution, `touch()` version/updated_at cascade, schedule journaling, risk refresh |
| `calc.py` | 245 | All six calculations in Decimal HALF_UP 2dp |
| `sweeps.py` | 141 | Clock-fired sweeps + system DRAFT-cycle factory |
| `serializers.py` | 57 | Exact scaffold field sets; `_`-prefixed internals never emitted |
| `routes/*.py` | 2188 | 71 routes across 12 modules (admin, templates, vendors, cycles, responses, evidence, exceptions, plans, acceptances, addenda, monitoring, attestations) |

Total 3039 lines.

## Subsystem implementations

- **State machines**: all 12 lifecycles implemented transition-by-transition with `ERR_INVALID_STATE` (409) precondition checks, including the cyclic questionnaire revision loop (RETURNED→SUBMITTED resubmission), template DRAFT→PUBLISHED→RETIRED plus revise-to-new-DRAFT (inherits `published_version`), and the remediation verify-reject compensation (exceptions back to OPEN).
- **Calculations**: `tier_assignment` (tier-matrix override accepting multiple key-separator spellings, else rank-sum 7/5/3 cutoffs); `questionnaire_response_score` (NA excluded from both sums, raw = HALF_UP(100·earned/possible), penalty = min(raw·5%·revision_count, 20), fail branch is a workflow outcome not an error per PRD); `evidence_review_score` (per-kind base 100/95/80/70/50, gap penalty normalized over 180d for TIER_3/4 vs 365d for TIER_1/2, EVIDENCE-source severity deductions 25/15/8/3, REJECTED excluded, floored at 0); `composite = 0.4Q + 0.6E`; `vendor_risk_score` (posture base + alert/residual-acceptance/imminent-expiry modifiers, clamped [0,100]); `addendum_requirement` (sorted union of tier base clauses + HIGH→C_REMEDIATION_TIMELINE / CRITICAL→C_TERMINATION_RIGHT); response windows 45/30/21/14d and pass thresholds 60/70/80/90.
- **OCC**: `expected_vendor_version` on cycle create → `ERR_STALE_VENDOR_VERSION` (412); `expected_cycle_version` on risk-acceptance approve → `ERR_STALE_CYCLE_VERSION` (412); both non-optional (missing → 422), checked at priority 6 before uniqueness/posture gates.
- **SoD**: five gated pairs enforced (acceptance approve/reject vs requester, plan verify vs `approved_by`, subprocessor approve vs review-starter, cycle approve vs evidence-review completer) → `ERR_SEGREGATION_OF_DUTIES` (422); tracked in internal `_`-fields that are never serialized.
- **Clock/sweeps**: logical clock only (never wall clock), default `2026-08-01T00:00:00Z`; `POST /vsa/_clock/set_current_utc` fires three sweeps in order — cycle ISSUED→EXPIRED past `response_due_at` (vendor→SUSPENDED, due→now+tier4 months, ALERT_ESCALATION event), acceptance APPROVED→EXPIRED past `expires_at` (exceptions reopen with `closure_reason=ACCEPTANCE_EXPIRED`, min-semantics 30-day pull-forward, ACCEPTANCE_EXPIRY event), and reassessment-due (APPROVED/CONDITIONAL vendor→ASSESSING with fresh template-less DRAFT cycle). Every swept resource gets its own version bump per PRD §2.11.
- **Cascades**: exception open/close adjusts `cycle.open_exception_count` with cycle version bumps; plan accept → exceptions IN_REMEDIATION; verify → CLOSED_REMEDIATED; acceptance approve → CLOSED_ACCEPTED + `acceptance_required=true`; artifact reject auto-creates HIGH EVIDENCE exception; evidence-review completion branches REMEDIATION (generates REQUIRED ContractAddendum) / RISK_ACCEPTANCE_REVIEW (accepted exceptions exist) / clean-pass APPROVED (TIER_CADENCE event, cadence due); cycle approve → CONDITIONAL (halved cadence) when any APPROVED acceptance exists; escalation/due-sweep DRAFT cycles get auto template selection at issue (highest `published_version` eligible); offboard→attestation REQUESTED (+90d deadline); attestation reject→fresh REQUESTED + 30d slip (OFFBOARDING_SLIP); verify→OFFBOARDED with `next_reassessment_due` nulled.

One deliberate spec-tension call: escalation/sweep-created DRAFT cycles sit on vendors in ASSESSING posture, so `issue` accepts ASSESSING in addition to the PRD's ONBOARDING/APPROVED/CONDITIONAL list — otherwise an escalated vendor is permanently wedged (a new cycle can't be created while one is active).

## Verification

~90 behavioral assertions passed across four smoke suites covering: envelope shape, 401/403/404 precedence, VC scoping (own-vendor only, unknown contact → 403), pagination bounds, tier matrix override vs rank fallback, OCC 412s, publish uniqueness per tier set, retire-in-use 409, score math incl. revision penalty (83.33 → 79.16), evidence/composite math (82.45/89.47, 49.92/56.62), remediation SoD, acceptance OCC+SoD+expiry reopen, escalation pull-forward (CRITICAL +14d), expiry sweep, offboarding compensation loop, CONDITIONAL halved cadence (24mo→18mo), and reassessment-due sweep. Confirmed `bash start.sh` boots on `$PORT` bound to `0.0.0.0` in the foreground, and a kill/restart cycle wipes all state with the clock back at the default.

## Step 7: Run Tests and Iterate — 2026-08-13T09:48:46.198Z

All 8 rounds pass: 78/78 in every round. Clean sweep achieved.

## Summary

**Iterations run:** 2 (baseline sweep: 75/78 × 8 rounds with 3 stable failures; post-fix sweep: 78/78 × 8 rounds, zero failures, zero flakes).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None — the shared fixture chain (`setup_scored_cycle`, `upload_evidence`, `review_artifact_clean`) was already PRD-faithful; the bug was in the test file's own constants.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/test_suite/test_04_evidence_review.py` — 3 tests fixed (STEP 2: test wrong, not implementation):
  - `TestEvidenceScoreMultiInput::test_gap_penalty_and_severity_deduction_combine`
  - `TestEvidenceScoreMultiInput::test_without_exceptions_clean_pass_approves`
  - `TestCompositeScore::test_composite_is_forty_sixty_weighted`

  **Root cause:** All three set up a SOC2_TYPE2 artifact with `GAP_365_EVIDENCE` (period_end 2025-08-01 vs issuance 2026-08-01 → `coverage_gap_days` = 365) and then called complete-review on it. PRD §3.5 states verbatim: "Completing a review on an artifact whose gap exceeds 180 days likewise fails coverage validity with `ERR_EVIDENCE_COVERAGE_INVALID` (HTTP 422)." The implementation correctly enforced this (confirmed by the already-passing `test_gap_181_fails_coverage_validity`, which asserts the same check), so the setup could never reach the scoring assertions on any PRD-faithful implementation — the 365-day cap in the standard-window formula is unreachable for completable artifacts.

  **Fix:** Replaced `GAP_365_EVIDENCE` with `GAP_MAX_SOC2_EVIDENCE` (gap exactly 180 days — the maximum completable) and changed `setup_scored_cycle()` → `setup_scored_cycle(tier="TIER_3")` so the strict 180-day window yields the full 30-point penalty: 100 − min(180,180)/180×30 = 70, identical to the originally intended 100 − 365/365×30 = 70. Every asserted number (evidence 67.5 / 82.5, composite 80.5, APPROVED verdict — 89.5 ≥ 80 TIER_3 threshold) is unchanged; only the setup became PRD-legal. Docstrings updated to reflect the TIER_3 strict-window rationale.

**Fixes applied to `implementation/`:** None — the implementation was fully correct; every failure traced to the test-side setup violating a PRD-mandated coverage-validity check.

**Feedback note for generators:** the three tests were generated from the scaffold's `evidence_score_multi_input_tiered_mode_a` / `composite_score_weighted_40_60` designs, which exercised the 365-day standard-window cap at TIER_1 without accounting for the scaffold's own `COVERAGE_GAP_REJECT_DAYS = 180` completion ceiling — the scenario was self-inconsistent (a formula branch that no legal state path can reach).

## Step 8: Finalize PRD — 2026-08-13T09:56:23.587Z

`PRD_FINALIZED.md` is written and byte-identical to `PRD.md`. Here is the exit summary.

## Summary

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1442_vendor_security_assessment_evidence/workspace/PRD_FINALIZED.md` — verbatim copy of `PRD.md`, **zero edits**.

**Line counts / %-delta:** PRD.md 347 lines; PRD_FINALIZED.md 347 lines; delta 0 lines, 0.0%. `diff` confirms byte-identity.

**Changes (one bullet per change):** None. The single `<step_7_diff>` item (3 tests fixed in `test_suite/test_04_evidence_review.py`; no implementation fixes, no helper fixes, no deletions) is a **pure test-fixture bug**, not a PRD silence or PRD/impl mismatch: the tests set up a SOC2_TYPE2 artifact with a 365-day coverage gap and called complete-review on it, which PRD §3.5 already forbids verbatim ("Completing a review on an artifact whose gap exceeds 180 days likewise fails coverage validity with `ERR_EVIDENCE_COVERAGE_INVALID`"). The implementation enforces exactly that (`evidence.py:104-108`). The fix made the setup PRD-legal (gap exactly 180, TIER_3 strict window → same 70-point contribution); every asserted value (evidence 67.5 / 82.5, composite 80.5, REMEDIATION / APPROVED branches) was already uniquely determined by the PRD and matched by the implementation. Per Method step 1, no patch is warranted.

**Per-edit pre-edit search log:** No edits were committed, so there are no per-edit logs. In place of it, the verification search that produced the no-edit conclusion:

- **(a) Subject identified:** every behavioral choice exercised by the three fixed tests — the 180-day complete-review ceiling, the dual-window (365/180) coverage-gap penalty keyed on tier-at-issue, base-by-kind values, severity deductions, REJECTED-artifact exclusion, zero-floor + round-half-up, the 40/60 composite, tier pass thresholds, and the REMEDIATION-vs-APPROVED completion branches (including the scaffold's "unreachable 365-day cap" concern from the feedback note).
- **(b) Impl paths enumerated and read:** `implementation/routes/evidence.py` (upload validity check lines 60-62; `complete_review` gap computation and `> 180` rejection lines 104-108; reject path lines 120-148); `implementation/calc.py` (`evidence_review_score` lines 106-130 incl. `strict = tier_at_issue in ("TIER_3","TIER_4")` and `cap = 180 if strict else 365`; `composite_cycle_score` lines 138-140; `recompute_acceptance_required` lines 143-154; `PASS_THRESHOLD` lines 59-60); `implementation/routes/cycles.py` (`complete_evidence_review` lines 292-341 incl. pending-artifact gate, REMEDIATION + addendum branch, clean-pass gates, `_approve_vendor_side_effects` lines 344-361); plus `test_helpers/fixtures.py` (`setup_scored_cycle`, `setup_evidence_review_cycle`, `review_artifact_clean`), `test_helpers/constants.py` (`TIER_PROFILES`), `test_helpers/assertions.py` (`assert_score`), and the full fixed test file. Cross-checked each against PRD §2.9 item 13, §2.10, §3.5 (lines 185-191), §3.7 (line 207), and §5 catalogue.
- **(c) Wording adjustment:** n/a — every enumerated path is already uniquely and verbatim determined by PRD.md (the 365-day cap is shared identically by spec and impl and is unobservable for all completable artifacts since `min(gap,365) = gap` whenever gap ≤ 180, so no fresh implementer can diverge). Any insertion would have been editorializing beyond the Step 7 scope, risking a NO-NEW-MISMATCH violation.

## Step 9: Complete PRD — 2026-08-13T10:27:24.198Z

The completed PRD is written. Final summary:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (347 lines / 57,702 chars) → `PRD_COMPLETED.md` (347 lines / 62,923 chars; **+0 lines, +5,221 chars**). `PRD_FINALIZED.md` was byte-identical to `PRD.md`. All changes are in-paragraph inserts/revisions; no sections added.

**Counts:** 30 ambiguity-pins, 3 mismatch-revisions (33 changed passages total; 32 diff hunks).

**Mismatch revisions:**
- §3.4 — revise — mismatch — removed the claim that a provisional raw score is computed at submission; impl leaves `raw_score` null until the scoring endpoint runs — implementation/routes/responses.py:73-116 (no scoring in `submit_response`), routes/cycles.py:277 (raw_score set only in `score_cycle`).
- §3.3 — revise — mismatch — issuance posture set now includes `ASSESSING` (PRD listed only ONBOARDING/APPROVED/CONDITIONAL); also pinned that DRAFT/posture/active-cycle precondition failures yield `ERR_INVALID_STATE` (409) — implementation/routes/cycles.py:26, 205-217.
- §2.6 — revise — mismatch — clock advance fires three sweeps (added the reassessment-due sweep of §3.8, run in impl order: cycle expiry, acceptance expiry, reassessment-due), not just the two the PRD named — implementation/sweeps.py:115-119.

**Ambiguity pins (one per change):**
- §2.1 — insert — a `VendorContact` whose `X-User-ID` matches no persisted contact sees nothing: flat/vendor lists empty, vendor-scoped reads/writes 403 — implementation/middleware.py:53-73.
- §2.3 — insert — non-integer `limit`/`offset` rejected `ERR_PAGINATION_INVALID`; `created_at` sort ties break by insertion order — middleware.py:77-107.
- §2.4 — revise — `version` starts at 1 on creation — implementation/helpers.py:20-28.
- §2.6 — insert — all server-emitted timestamps (`created_at`, `updated_at`, envelope `api_request_timestamp`, etc.) read the logical clock; `to_iso8601` missing/unparseable → `ERR_INVALID_REQUEST` (422); any instant accepted, forward or backward — implementation/response.py:16-26, helpers.py:22-37, routes/admin.py:19-33.
- §2.7 — insert — both OCC guards compare by exact equality; missing/null/non-integer guard → `ERR_INVALID_REQUEST` (422) — routes/cycles.py:46-57, routes/acceptances.py:104-115.
- §2.9 — insert — cascade yields where an endpoint section states a more specific ordering (needed for the §3.6 acceptance-create order) — reconciles with routes/acceptances.py:40-62.
- §3.1 — insert — vendor's `next_reassessment_due` is null at registration — routes/vendors.py:47-58.
- §3.1 — insert — policy creation validates `name`/`tier_matrix` presence, matrix values in TIER_1..4, cadences positive integers (all `ERR_INVALID_REQUEST`); `active` filter accepts only `true`/`false` case-insensitively, other values unfiltered — routes/admin.py:38-90.
- §3.1 — insert — **`tier_matrix` key serialization pinned**: triple joined in sens-access-crit order by any of `,` `|` `:` `;` `/` `+` space `-` (tried in that order), plus JSON array with spaces, compact JSON array, and Python-tuple repr spellings — implementation/calc.py:20-35.
- §3.1 — revise — any vendor PATCH (even `legal_name`-only) re-runs tier assignment — routes/vendors.py:94-118.
- §3.1 — insert — duplicate contact email → `ERR_UNIQUENESS_VIOLATION` (409) — routes/vendors.py:164-167.
- §3.2 — insert — item `weight` must be numeric at authoring, positivity enforced only at publication; publish tier-set refusal is `ERR_UNIQUENESS_VIOLATION` (409); `published_version` starts at 0 (first publish → 1); revise copies `title`, `applies_to_tiers`, and items — routes/templates.py:22-67, 87-107, 134-152.
- §3.3 — insert — cycle creation permitted postures enumerated: ONBOARDING, APPROVED, CONDITIONAL, SUSPENDED — routes/cycles.py:21, 66-69.
- §3.3 — insert — platform-created DRAFT cycles (escalation/reassessment sweep) carry no `template_id`; issuance adopts the eligible PUBLISHED template with highest `published_version` (earliest-created tiebreak), else `ERR_TEMPLATE_NOT_PUBLISHED` — routes/cycles.py:236-254.
- §3.3 — insert — expiry sweep cadence defaults to 6 months when no policy is active — sweeps.py:32-34.
- §3.4 — insert — drafting requires cycle `ISSUED` (else `ERR_INVALID_STATE`); `submitted_by` recorded verbatim with no identity cross-check; multiple drafted responses per cycle allowed — routes/responses.py:32-70.
- §3.4 — insert — resubmission changes only response status/version; `submitted_at` not restamped, cycle untouched — routes/responses.py:110-115.
- §3.5 — insert — uploads accepted in `SCORED` or `EVIDENCE_REVIEW` (later uploads don't re-transition) — routes/evidence.py:40-42, 74-77.
- §3.5 — revise — review exit is `REVIEWED_WITH_EXCEPTIONS` iff any referencing exception is in a status other than `CLOSED_FALSE_POSITIVE` (PRD said "no OPEN exception") — routes/evidence.py:109-115.
- §3.5 — insert — artifact rejection is not gated on the warrant conditions; any `UNDER_REVIEW` artifact may be rejected — routes/evidence.py:120-148.
- §3.5 — insert — on the clean-pass path, an outstanding REQUIRED/DRAFTED addendum yields `ERR_OPEN_ITEMS_OUTSTANDING` — routes/cycles.py:334-337.
- §3.5/§3.7 — insert — approval cadence defaults to 12 months when no policy is active — routes/cycles.py:348-350.
- §3.6 — insert — exception creation, plan proposal, and acceptance request are not gated on cycle status — routes/exceptions.py:22-63, routes/plans.py:48-80, routes/acceptances.py:31-76.
- §3.6 — insert — non-EVIDENCE exception discards a supplied `evidence_artifact_id` (stored null) — routes/exceptions.py:43-44.
- §3.6 — insert — plan `tasks` must be non-empty — routes/plans.py:31-34.
- §3.6 — insert — progress reports accumulate: `completed_task_keys` is the sorted union of all keys reported so far — routes/plans.py:140-147.
- §3.6 — insert — verification closure text comes from body `closure_reason`, else `note`, else literal `REMEDIATION_VERIFIED` — routes/plans.py:171-172.
- §3.6 — insert — acceptance-create validation order: field/format checks, then future-`expires_at`, then referential integrity (deviates from §2.9's generic 7-before-8) — routes/acceptances.py:40-62.
- §3.7 — insert — remediation resolve with undecided plans/open exceptions → `ERR_OPEN_ITEMS_OUTSTANDING` (422) — routes/cycles.py:371-375.
- §3.7 — insert — CONDITIONAL cadence halving uses integer floor arithmetic — routes/cycles.py:351-352.
- §3.7 — insert — addendum sign: missing/unparseable/future `signed_at` → `ERR_INVALID_REQUEST` (422) — routes/addenda.py:59-66.
- §3.8 — insert — "most recent APPROVED cycle" = most recently created — implementation/calc.py:178-184.
- §3.9 — insert — subprocessor filing blocked only in `OFFBOARDING`/`OFFBOARDED` — routes/monitoring.py:27, 170-173.
- §3.9 — insert — offboard from a non-permitted posture, or with a cycle in flight where restricted, → `ERR_INVALID_STATE` (409) — routes/vendors.py:121-131.

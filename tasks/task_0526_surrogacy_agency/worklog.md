# Worklog — task_0526_surrogacy_agency

## Step 1: Create Task Directory — 2026-07-01T04:14:24.000Z

Used pre-specified folder `tasks/task_0526_surrogacy_agency` (skipped auto ID scan per instruction). Created `tasks/task_0526_surrogacy_agency/workspace`. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-01T04:29:00.000Z

Subagent generated SCAFFOLD.yaml (1703 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml. Two design files initially failed `yaml.safe_load` (unquoted bracketed JSONPath in flow mappings + `errors[...]` tokens in flow `grounds:` lists); fixed by the same subagent. All three now parse cleanly; SCAFFOLD.yaml has no design-key leakage. Subagent summary verbatim:

All checks pass. Summary of what I generated for `task_0526_surrogacy_agency` (Surrogacy & Egg-Donation Agency, **Expert** difficulty):

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Complexity profile**: primary archetype `multi_party_negotiation` + secondary `compliance_audit`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; flat topology, cyclic state-machine shape, segregation_of_duties role model.
- **11 entities**: IntendedParent, GestationalCarrier, EggDonor, Match, Contract, EscrowAccount, Journey, Milestone, CompensationSchedule, Disbursement, InsuranceReview. 12 FKs, all with reverse-reachability GETs.
- **10 state machines** including non-linear shapes: Match negotiation cycle (PROPOSED↔COUNTERED, offer_round), Disbursement branching (REQUESTED→{APPROVED,REJECTED}, APPROVED→REJECTED/RELEASED with divergent escrow side-effects), plus cascade chains (match void → contract void → escrow freeze; journey terminate → escrow freeze).
- **5 calculations**: escrow_available_reconciliation (aggregation invariant), escrow_disbursable_now (gated/chronological) vs escrow_projected_liability (forward-looking) — a dual-variant pair on EscrowAccount; carrier_total_compensation (tiered + conditional, mode-a) and insurance_gap_premium (nested rounding, mode-b).
- **16 validations** (priority-ordered, spanning auth/existence/state/safety/referential/temporal/constraint/fiscal), **19 errors**, **5 roles** (CaseManager, Screener, FinanceOfficer opaque; IntendedParentActor/CarrierActor entity_backed), **2 concurrency_rules** (OCC on Match.version and EscrowAccount.version).
- **76 endpoints** (includes single-resource + filtered-list + sub-resource GETs for FK reverse-reachability, and a `/_clock/set_current_utc` test-driving endpoint with default 2026-05-01T00:00:00Z).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids × 2 = **18 instances**, each with executable empty-DB `setup_api_calls` chains, literal-pinned asserts (e.g. gap_premium 540000 vs sum-then-round 540004; comp total 4200000; disbursable_now 1000000 vs projected_liability 6000000; funding_shortfall 2000000).

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections, **30 active instances + 1 excluded_because stub** covering entity CRUD/not-found/required-field/system-field/listing, invalid-transition/precondition/terminal-lockdown/guarded transitions, calculation correctness, validation errors (jurisdiction/budget/milestone-gate/journey-precondition), RBAC denials, OCC stale-version, and derived-field recompute.

**Lint**: `VERDICT: clean lint` (76 endpoints, 11 entities, 18 §1.8 + 30 §1.9 instances, 696 calls scanned, 0 violations).

## Step 3: Copy INSTRUCTION.md — 2026-07-01T04:29:53.000Z

Copied ./INSTRUCTION.md → tasks/task_0526_surrogacy_agency/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-01T04:35:19.000Z

Subagent generated workspace/PRD.md (~295 lines) from SCAFFOLD.yaml only (design files withheld). Sections: §1 Intro, §2 Global Specs (RBAC, response envelope, pagination, common props, nested retrieval, monetary precision, OCC, segregation of duties, escrow reconciliation invariant, cascading consequences, logical clock), §3 Business Logic (10 lifecycle subsections), §4 Endpoint table, §5 Error catalogue (19 IDs). Hard-contract self-checks: field coverage PASS (36/36 fields, 15/15 bodies), rule coverage PASS (16 validations, 2 OCC, 10 state machines, 5 calculations), path-purity PASS (0 path tokens in §3). Withheld difficulty/corner files not opened.

## Step 5: Generate Unit Tests — 2026-07-01T04:56:00.000Z

Subagent generated test_helpers/ (9 files) + test_suite/ (conftest + 8 test files, **66 tests**). Queue A (Difficulty): 18/18 instances × 2 tests = 36. Queue B (Corner): 30/30 non-stub instances × 1 = 30. Every test docstring carries a verbatim PRD citation + `Design:` tag. Coverage audit machine-verified: 0 orphan tags, 0 translated stubs, 0 skip/xfail, 0 scaffold-leak refs, all quoted PRD fragments grep verbatim, 66 collect cleanly. Skipped: 1 (`Corner/consistency_model/disbursement_approve_visible_reserved_in_same_response` — an `excluded_because` stub, correctly not translated). No PRD-first filter rejections.

## Step 6: Generate Implementation — 2026-07-01T04:56:00.000Z

Subagent generated workspace/implementation/ (11 files: start.sh, requirements.txt, app.py, db.py, errors.py, response.py, middleware.py, clock.py, calculations.py, serialize.py, validate.py). ~70 endpoints across 11 entities + `/_clock/set_current_utc`. 10 state machines, calculations (insurance_gap_premium, carrier_comp_breakdown, escrow_disbursable_now, escrow_projected_liability/funding_shortfall, escrow invariant). Cascades verified (match-void→contract-void→escrow-freeze; journey-terminate→escrow-freeze). In-memory only, no seeding; start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec. Self-verified 3 e2e suites pass, fresh boot empty state, clock default 2026-05-01T00:00:00Z.

## Step 7: Test-and-Fix Loop — 2026-07-01T04:57:48.000Z

Long-lived fix subagent converged to a clean 8-round parallel sweep (64/64 all rounds). Orchestrator re-ran a confirming 8-round sweep: rounds 1–8 all 64/64 PASS; results.1–8.json persisted in implementation/. Subagent summary verbatim:

**Iterations run:** 4 sweeps (1 baseline diagnostic + 3 fix-and-verify; last two both clean 64/64 across all 8 rounds). Baseline: 61/66; union of 5 stable failures diagnosed; ended at 64/64.

**Tests deleted (2):**
- `test_contract_void_freezes_open_escrow` (test_03) — STEP 1b unreachable-state / BRANCH-ASYMMETRIC SIDE EFFECT. PRD §3.4 restricts a *direct* contract void to DRAFTED/IP_SIGNED, but an OPEN escrow only exists once a journey is active (requires an EXECUTED contract). "Direct void freezes the open escrow" is PRD-unreachable; fixture built an EXECUTED contract and the PRD-faithful impl correctly rejected the direct void with ERR_INVALID_STATE.
- `test_clear_intended_parent_without_psych_passed_rejected` (test_08) — ERROR PRECEDENCE SILENCE. PRD §3.1 states the IP-clear precondition (psych_clearance PASSED) but names no error id for its violation. A faithful implementer could return ERR_INVALID_STATE or ERR_PSYCH_CLEARANCE_MISSING; test pinned the former, impl returned the latter. Not uniquely derivable.

**Fixes to test_suite/:**
- test_05, `test_distinct_milestone_types_allowed_on_same_journey` — assertion bug: validate_success defaulted to HTTP 200 but PRD §4 says creation returns 201; passed expected_status=201.

**Fixes to test_helpers/:** none.

**Fixes to implementation/:**
- app.py, `match_void` (cascade hop-one) — removed the `if c["status"] in ("DRAFTED","IP_SIGNED")` guard so the match-void cascade voids *any* non-VOID linked contract (PRD §3.4 hop-one has no state restriction, unlike the direct void endpoint). Fixed 2 cascade tests. Direct contract_void restriction left intact.
- app.py, `__main__` — replaced `app.run(threaded=True)` with an explicit threaded Werkzeug server (request_queue_size 256, daemon threads) because the default socket backlog saturated under 8× concurrent per-test-server load (BadStatusLine/ConnectionError in 2/8 rounds of sweep 2). Storage remains in-memory, wiped on every start.sh reboot.

Key finding: the only genuine implementation defect was the over-restrictive match-void cascade; the rest were test-artifact issues plus a concurrency-robustness bootstrap fix.

## Step 8: Finalize PRD — 2026-07-01T05:00:00.000Z

Subagent produced workspace/PRD_FINALIZED.md as a minimal patch of PRD.md targeting the <step_7_diff> items. One edit applied. Subagent summary verbatim:

The finalized PRD is written. One edit applied.

## Summary

**PRD.md vs PRD_FINALIZED.md**: 295 lines → 295 lines (0 line-count delta; one line revised in place). Character-level: +1 clause added. %-delta ≈ 0% by line count, ~1 sentence-clause changed.

### Changes (1)

- **§3.1 (Intended-Parent intake) — revise — pinned the error id for the IP-clear psych precondition violation: added "when the record is in `SCREENING` but its `psych_clearance` is not `PASSED`, clearing is rejected with `ERR_PSYCH_CLEARANCE_MISSING`" — app.py:230-231**

### Items examined that required NO edit

- **`match_void` cascade hop-one (app.py:694-700)** — PRD §3.4 already pins hop-one as voiding the linked contract "if such a contract exists and is not already `VOID`" with no state restriction. The Step 7 fix aligned impl *to* the existing PRD; PRD was never silent here. No edit.
- **`__main__` threaded server (app.py:1356-1370)** — pure concurrency/bootstrap robustness, no observable API behavior. No edit.
- **Deleted test `test_contract_void_freezes_open_escrow`** — PRD-unreachable state (direct void restricted to DRAFTED/IP_SIGNED per §3.4, but OPEN escrow requires EXECUTED contract). PRD already determines the direct-void restriction; impl correctly rejects. No silence. No edit.
- **test_05 status-code fix (201)** — PRD §4 already states creation returns 201 Created. Pure fixture bug. No edit.

### Per-edit pre-edit search log

**Edit 1 — IP-clear error id**
- **(a) Subject**: error id returned when clearing an applicant whose `psych_clearance` is not `PASSED`.
- **(b) Impl paths enumerated/read** (grep of `ERR_PSYCH_CLEARANCE_MISSING`, `psych_clearance`, `intake_status`, `PASSED`, `CLEARED` across app.py):
  - app.py:230-231 `ip_clear` — the Step 7 site: psych ≠ PASSED → `ERR_PSYCH_CLEARANCE_MISSING`.
  - app.py:335-336 `carrier_clear` — parallel path: psych ≠ PASSED → same error, but PRD §3.1/§3.2 carrier-clear sentence is a distinct sentence not in this edit's scope.
  - app.py:656-663 `match_accept` — party `intake_status` ≠ CLEARED → `ERR_PSYCH_CLEARANCE_MISSING` (already pinned in PRD §3.3).
  - app.py:679-682 `match_psych_clear` — party psych ≠ PASSED → same error (already pinned in PRD §3.3).
- **(c) Wording adjustment**: Scoped the new clause strictly to the intended-parent record ("the record is in `SCREENING` but its `psych_clearance` is not `PASSED`") so it makes no universal claim that would mis-describe the carrier-clear path (which also has the `ERR_INSURANCE_REVIEW_REQUIRED` case and its own §3.1 sentence) or the match-level paths. No widening/softening beyond this local scoping was needed; the two match-level paths already carry the same error id in the PRD, so consistency holds.

## Step 9: Complete PRD — 2026-07-01T05:05:00.000Z

Subagent produced workspace/PRD_COMPLETED.md via a full PRD-vs-implementation/ scan, starting from PRD_FINALIZED.md. 10 edits (9 ambiguity-pins + 1 mismatch-revision). Subagent summary verbatim:

## Summary

**Line/char counts:** `PRD_FINALIZED.md` (source) = 295 lines / 43,506 chars → `PRD_COMPLETED.md` = 295 lines / 45,044 chars (**+1,538 chars, 0 new lines**; all edits are in-paragraph). 11 lines changed.

**Counts:** ambiguity-pins = 9, mismatch-revisions = 1. (Total 10 edits across the file.)

**Per-change:**
- §2.3 Pagination — insert — ambiguity — pinned that ties on identical `created_at` are broken by server-side creation order — `validate.py:100` (`sort_by_created` uses `(created_at, _seq)`).
- §2.4 Common Properties — insert — ambiguity — pinned `version` initial value = `1` — `db.py:51` (`obj["version"] = 1`).
- §3.1 IP screening — insert — ambiguity — pinned that recording IP `psych_clearance` (`set-psych`) has no `intake_status` precondition — `app.py:213-221` (`ip_set_psych`, no state check).
- §3.1 Carrier screening — insert — ambiguity — pinned that setting carrier `psych_clearance` has no `intake_status` precondition — `app.py:318-326` (`carrier_set_psych`, no state check).
- §3.2 Insurance outcomes — insert — ambiguity — pinned `ERR_INVALID_STATE` when review not `PENDING` or `policy_kind` mismatches the outcome — `app.py:492-495,505-508,521-524`.
- §3.4 Contract drafting — insert — ambiguity — pinned that a contract may be drafted for any existing match (no `PSYCH_CLEARED` precondition at draft; enforced later at IP-sign) — `app.py:716-730` (`create_contract` only does `lookup_or_404`).
- §3.5 Journey complete — insert — ambiguity — pinned `ERR_INVALID_STATE` when journey not `ACTIVE`, `BIRTH` not `ACHIEVED`, or parentage not `GRANTED` — `app.py:907-916`.
- §3.7 Disbursable-now — **revise — mismatch** — PRD said the walk "stops contributing further" after the first over-cap skip; impl does NOT stop — it continues and admits any later line that still fits — `app.py:1126-1128` (loop with no `break`).
- §3.7 Projected liability — insert — ambiguity — pinned that a schedule line whose trigger milestone type has no milestone record yet on the journey is treated as not-`FAILED` and included — `app.py:1133-1135` (`m is None or ...`).
- §3.6 Parentage file/decide — insert — ambiguity — pinned `ERR_INVALID_STATE` for file when not `NOT_FILED` and for decide when not `FILED`, and `ERR_INVALID_REQUEST` for a bad `decision` — `app.py:938-939,954-956`.
- §3.9 Escrow unfreeze/close — insert — ambiguity — pinned `ERR_INVALID_STATE` for unfreeze blocked by a `VOID` contract and for close failing any of its three conditions — `app.py:1188-1207`.

**Notes on non-changes:** created_at/updated_at wall-clock use is already pinned by §2.11's explicit two-item scope of the logical clock; match-accept OCC-before-clearance ordering is already pinned by §3.10; disbursement-approve check order matches §3.8 prose. No new behavior was invented.

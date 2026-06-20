# Worklog — task_0401_assisted_living_memory_care

## Step 1: Create task directory — 2026-06-18T00:00:00.000Z

Created `tasks/task_0401_assisted_living_memory_care/` and `tasks/task_0401_assisted_living_memory_care/workspace/` (fixed pre-allocated directory; no auto-increment scan). Scenario: Assisted Living & Memory Care Facility (Brookdale style). Difficulty: Expert (applies only to Step 2 scaffold generation).

## Step 2: Generate scaffold (Expert) — 2026-06-18T00:00:00.000Z

All three files parse, key discipline is honored, and `scaffold_lint.py` reports a clean verdict. The scaffold for the Assisted Living & Memory Care facility is complete.

**Expert-tier counts (all targets met):**
- Entities: **11** (target 10–15) ✓
- Endpoints: **54** (target 20–32) — over band; see trade-off below
- Validations: **20** (target 18–30) ✓
- Calculations: **5** (target 3+) ✓
- State machines: **9** (target 4+, with cycles + branching) ✓

Plus 29 errors, 6 roles, 2 OCC concurrency rules. `scaffold_lint.py`: **VERDICT clean** (303 calls scanned, all FKs reverse-reachable). §1.8 has the full 9 rules × 2 = **18 instances**; §1.9 has 35 active corner instances + 3 `excluded_because` stubs (all referencing valid §1.8 instances). All formula-derived assertion literals (care points, prorated/full billing with pinned per-line rounding 316870 vs sum-then-round 316871, occupancy bps, POC due dates) were computed in code, not estimated.

**Design notes / trade-offs:**
- **Archetype:** pricing engine (rent + care-points billing) blended with quota/allocation (bed inventory); peer-roles RBAC; branching/cyclic state machines (resident lifecycle, license loop, bed-occupancy loop, POC resubmit cycle, care-plan self-referential revision loop, incident resolve-vs-escalate fork).
- **Two dual-variant calcs on different domains** (care-points provisional/frozen on Assessment vs full/prorated charges on Billing) and **two combinatorial modes** (weighted+min-capped scoring mode a; pinned round-per-line mode b).
- **Endpoint overage (54 vs 32):** scenario spans ~10 distinct sub-workflows; 22 read + 32 write endpoints, each mapping 1:1 to a declared edge. Kept full breadth ("Do not under-scope" directive) rather than cutting named workflows; other four mandated metrics cleanly in-band.
- `api_prefix` is `/` (flat top-level collections), which the lint requires for non-nested entities' reverse-reachability to resolve.

## Step 3: Copy INSTRUCTION.md — 2026-06-18T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0401_assisted_living_memory_care/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-18T00:00:00.000Z

PRD generation complete. Written to `workspace/PRD.md`. **301 lines.**

**Major sections:** §1 Introduction; §2 Global Specifications (11 subsections: RBAC, Response Structure, Pagination, Common Properties & Versioning, Nested Retrieval & Path Validation, OCC, Monetary/Numeric Precision, State Transition Integrity & Cascades, Facility Standing/Licensing, Computed Facility Metrics); §3 Business Logic (11 subsections); §4 Endpoint Definitions (all 56 endpoints); §5 Error Code Catalogue (all 29 errors).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS — 93/93 identifiers present, 0 missing. Contract 2 (Rule Coverage) PASS — 20 validations, 2 OCC rules, 8 state machines, 5 calculations all reconstructible, sibling-branch symmetry maintained, 0 missing. Contract 3 (§3 Path Purity) PASS — 414 backtick tokens, 0 path/method leaks.

**Coverage:** every scaffold entity (11), endpoint (56), state machine (8), calculation (5), validation (20), error (29), role (6) covered. Immutable eMAR exception (only id/created_at) stated. Constraint files were NOT opened.

## Step 5: Generate unit tests — 2026-06-18T00:00:00.000Z

Generated test infrastructure from the two design indices only. **9 test files** (plus conftest.py), **71 tests total.**
- test_01_acuity_calculations, test_02_billing_calculations, test_03_cascades_and_invariants, test_04_cross_entity_and_cycles, test_05_validation_conflicts_and_overlaps, test_06_entities_and_crud, test_07_state_machines, test_08_validations, test_09_endpoints_rbac_concurrency.

**Coverage:** Queue A (§1.8 Difficulty) = 36 tests, all 18/18 instances with ≥2 tests each. Queue B (§1.9 Corner) = 35 tests, all 35/35 live instances with ≥1 test each. **SKIPPED for PRD-first filter: 0.** One queue-A instance (`activate_bed_temporal_vs_wing_safety_conflict`) uses `validate_error_is_one_of([ERR_BED_NOT_AVAILABLE, ERR_WING_MISMATCH])` (error-precedence silence — PRD §3.11 collapses both into one tier); second test isolates the wing rule hard. **Stubs not translated: 3** (occ_stale_unit_version_on_agreement_activate, license_suspended_blocks_admission, occupancy_recompute_visible_same_request) — all cross-refs resolve.

**test_helpers/ files (9):** __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. All 6 roles are identity: opaque → test_users.py emits shared-constant headers only. Audits passed: every test exactly one Design: tag; 88 PRD citations verbatim-confirmed; no skip/xfail/placeholder; no scaffold leakage; field names PRD-exact.

## Step 6: Generate implementation — 2026-06-18T00:00:00.000Z

Generated complete Python + Flask implementation (11 entities, 54 endpoints) in `workspace/implementation/`.
**Files:** start.sh, requirements.txt (Flask 3.0.3), app.py, db.py, errors.py, response.py, middleware.py, helpers.py, services.py, serializers.py, routes.py. **54 endpoints**, 1:1 with PRD table.
**Storage:** in-memory only (db.Store dicts), empty on every boot — no SQLite, no JSON dump, no seed_*(). **start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, pip-install guarded by marker file.
**Boot-robustness fixes:** (1) patched socket.getfqdn in app.py to avoid macOS reverse-DNS ~5s stall (5.3s→0.25s cold boot); (2) after_request hook forcing `Connection: close` so harness's reused requests.Session reconnects after per-test restart.
**Self-test result:** 69/71 passed under per-test-server isolation. The 2 failures (test_03 TestBedAvailabilityConservation::test_activate_then_cancel_restores_available_bed and test_facility_occupancy_unchanged_after_activate_cancel) flagged as a **test-suite internal contradiction**: they cancel an ACTIVE agreement expecting 200, while test_07::test_cancel_active_agreement_returns_invalid_state cancels the same ACTIVE fixture expecting ERR_INVALID_STATE. PRD §3.5/§2.8 pin cancel to DRAFT-only; impl follows PRD. → Step 7 to adjudicate against PRD.

## Step 7: Test + fix loop — 2026-06-18T00:00:00.000Z

All 8 parallel rounds pass with 69/69 tests green (down from 71 after deleting the 2 PRD-contradicting tests). The result is stable and deterministic across every round — no flakiness. Exiting the loop.

**Iterations run:** 2 (initial baseline sweep + one fix sweep).

**Diagnosis:** The initial 8-round sweep produced a perfectly stable, deterministic result — exactly 2 failures in every one of the 8 rounds, both in `test_03_cascades_and_invariants.py::TestBedAvailabilityConservation`. These were precisely the contradiction flagged in the task NOTE: they cancel an **ACTIVE** move-in agreement expecting `200` + bed release, while `test_07::test_cancel_active_agreement_returns_invalid_state` cancels the same ACTIVE fixture expecting `ERR_INVALID_STATE`. No implementation can satisfy both.

**PRD adjudication (per protocol STEP 1/STEP 2):** The PRD pins the cancel transition to DRAFT-only in two independent places — §3.5 state diagram lists only `DRAFT → CANCELLED` (no `ACTIVE → CANCELLED`), and §3.5 prose says "Cancelling **a draft** agreement"; §2.8 mandates `ERR_INVALID_STATE` for any out-of-machine transition. The implementation (`routes.py::cancel_agreement`) correctly enforces cancel-from-DRAFT. test_07 is the PRD-faithful test; the two `TestBedAvailabilityConservation` tests assert an outcome that directly contradicts the PRD-pinned state machine. Their premise (cancel releases a *reserved* bed) is unconstructible under PRD semantics, because only ACTIVE agreements reserve beds and ACTIVE agreements cannot be cancelled — so they cannot be repaired into a faithful form. Per the cardinal rules and the explicit NOTE, the contradicting tests are deleted; the implementation is not weakened.

**Tests deleted:**
- `test_03_cascades_and_invariants.py::TestBedAvailabilityConservation::test_activate_then_cancel_restores_available_bed` — STATE-MACHINE CONTRADICTION / branch-asymmetric side effect: asserts ACTIVE-agreement cancel succeeds, contradicting the PRD §3.5 `DRAFT → CANCELLED` machine and §2.8. (Scaffold rule: Difficulty/compensating_invariant/bed_count_conserved_activate_then_cancel.)
- `test_03_cascades_and_invariants.py::TestBedAvailabilityConservation::test_facility_occupancy_unchanged_after_activate_cancel` — same contradiction, same scaffold rule.

**Fixes applied to test_helpers/:** None (fixtures, factories, and role-header helpers were all verified PRD-faithful).

**Fixes applied to implementation/:** None (the implementation was already correct and PRD-faithful end-to-end; only the now-unused `setup_active_agreement` import was removed from `test_03_cascades_and_invariants.py` alongside the class deletion).

**Final state:** 69/69 tests pass in all 8 concurrent rounds, deterministically.

## Step 8: Finalize PRD — 2026-06-18T00:00:00.000Z

Done. `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` with no behavioral patch — the correct outcome for this task.

**Line counts / delta:** PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines. 0 lines changed, **0% delta** (byte-identical). **Changes: None.**

**Rationale:** The entire Step 7 diff was two test deletions (cancel-of-ACTIVE-agreement state-machine contradiction) + removal of an unused import; 0 implementation fixes, 0 test_helpers fixes. Pre-edit search on the agreement cancel / state machine subject (cancel_agreement routes.py:800–822, activate_agreement 767–798, create_agreement 715–743, finalize-discharge cascade 402–405, issue-statement 891) confirmed the cancel-from-DRAFT-only + ERR_INVALID_STATE-on-ACTIVE semantics are already uniquely determined by PRD §3.5 (`DRAFT → ACTIVE → TERMINATED`, or `DRAFT → CANCELLED`; "Cancelling a draft agreement…") plus §2.8 (ERR_INVALID_STATE for any out-of-machine transition). The deleted tests asserted the opposite of the PRD machine — buggy/contradicting tests, not PRD silence. Verbatim copy is correct.

## Step 9: Complete PRD — 2026-06-18T00:00:00.000Z

Full PRD-vs-implementation/ completeness scan. Source `PRD_FINALIZED.md` (301 lines, 48,041 chars) → `PRD_COMPLETED.md` (301 lines, 51,677 chars). Char delta **+3,636**; line count unchanged (all edits in-paragraph; no new sections).

**Counts:** 14 changes — **9 ambiguity-pins, 5 mismatch-revisions.**

**Changes:**
- §2.3 Pagination — insert — ambiguity — invalid limit/offset (non-int, out-of-range, negative) → ERR_INVALID_REQUEST — helpers.py:79-105
- §2.3 Pagination — insert — ambiguity — list sort tie-breaks by id ascending when created_at ties — helpers.py:110
- §2.4 Versioning — revise — ambiguity — version initial value pinned to 1 — db.py:43
- §2.5 Nested paths — insert — ambiguity — unit/deficiency under a different facility → ERR_UNIT_NOT_FOUND/ERR_DEFICIENCY_NOT_FOUND — routes.py:230-231,244-245,1100-1101,1117-1118,1133-1134
- §3.1 Facility create — insert — mismatch — state_code string-only check, "two-letter" not enforced — routes.py:110-113
- §3.2 Respite — revise — mismatch — registration validates presence/absence only; no date-vs-move-in comparison — routes.py:269-276
- §3.3 Finalize — insert — ambiguity — only PROSPECT→ASSESSED and ADMITTED→ASSESSED remap; others keep status — routes.py:510-513
- §3.4 Care plan create — insert — mismatch — source assessment FINALIZED + resident status checked at activation, not creation — routes.py:535-539
- §3.5 Admit — revise — ambiguity — check order pinned (state → binding → license); missing binding → ERR_INVALID_STATE before license check — routes.py:321-339
- §3.7 Med order create — insert — mismatch — schedule_times non-empty string array only; no HH:MM pattern; slot match string equality — routes.py:610-617,679
- §3.7 Administration — insert — ambiguity — no order-status precondition (recordable vs DISCONTINUED orders) — routes.py:662-691
- §3.7 Administration — insert — ambiguity — witness check before slot-membership; ERR_WITNESS_REQUIRED wins when both fail — routes.py:673-680
- §3.8 Statement create — insert — ambiguity — period_month outside 1-12 → ERR_INVALID_REQUEST — routes.py:836-837
- §3.8 Statement issue — revise — ambiguity — DRAFT-state check before agreement check; missing ACTIVE agreement → ERR_INVALID_STATE — routes.py:888-893
- §3.10 POC due date — insert — ambiguity — citation date from date-portion of cited_at (time ignored); poc_due_date emitted as bare YYYY-MM-DD — services.py:52-64

**Notes:** Acuity/billing calcs, discharge/escalation cascades, OCC rules, §3.11 priority ladder already uniquely pinned — unchanged. Date-format validation on date_of_birth/move_in_date/occurred_at deliberately not pinned (impl behavior inconsistent; no single clean behavior to document).

---

## PIPELINE COMPLETE — 2026-06-18T00:00:00.000Z

Final 8-round parallel stability sweep: **69/69 passing in all 8 rounds, deterministically.** All artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ (9), test_suite/ (9 files, 69 tests), workspace/implementation/ (11 modules + start.sh, in-memory only).

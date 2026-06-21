# Worklog — task_0121_quality_management_system

## Step 1: Create task directory — 2026-06-03T12:38:32.000Z

Task directory pre-allocated at `tasks/task_0121_quality_management_system/` with `workspace/` subdir already present. Did NOT scan ./tasks/ for next index per orchestrator instructions; used the exact pre-allocated directory. Verified: directory exists, workspace/ exists (empty), INSTRUCTION.md present at project root, prd-bench-local-run on PATH.

## Step 2: Generate scaffold (Expert) — 2026-06-03T13:38:39.000Z

Generated across three subagents (the initial single-agent run produced SCAFFOLD.yaml then hit a harness stream-idle timeout before the two design files; the design files were completed by two follow-up subagents using chunked incremental writes to avoid the timeout). Final consolidated `scaffold_lint.py` on the task dir: **clean lint, exit 0** — 47 §1.5 endpoints, 13 §1.1 entities, 18 §1.8 instances, 68 §1.9 instances, 583 calls scanned; all §1.8/§1.9 calls conform to §1.5 and all FKs have reverse-reachability.

SCAFFOLD.yaml structure: 13 entities, 8 state machines, 4 calculations, 15 validations, 47 endpoints, 20 errors, 5 roles. (Endpoint count 47 exceeds the Expert 20–32 guideline band; the linter's FK reverse-reachability requirement forces the overage and the scaffold is lint-clean — accepted per project convention.)

§1.8 difficulty-design subagent summary (verbatim):
> Created SCAFFOLD_DIFFICULTY_DESIGN.yaml with single top-level key scaffold_difficulty_design. Instances per rule_id (all 2 each, 18 total):
> - dual_variant_calc: 2 — capa_effectiveness provisional(0.60) vs final(1.00) on Capa; aql_sampling NORMAL(Ac=2) vs TIGHTENED(Ac=1) on InspectionLot — different entity domains.
> - combinatorial_formula: 2 — mode (a) supplier_quality_rating three-factor min/max → 57.00 PROBATION; mode (b) ncr_cost_of_quality round-per-line-then-sum → 4500. Different modes.
> - non_linear_state_machine: 2 — Capa cyclic VERIFICATION→ROOT_CAUSE (rework_loops=1); NonconformanceReport branching disposition fork (SCRAP 5000 vs RETURN_TO_SUPPLIER 500). Different entities.
> - transitive_cascade: 2 — depth-3 Capa-close → NCR CLOSED → Scar RESOLVED → Supplier rating 91→96; depth-2 lot-reject → consecutive_rejects=2 → severity_mode TIGHTENED. Different triggers.
> - priority_pair_validation_conflict: 2 — {state p6, business_safety p8} on disposition; {state p6, business_referential p7} on SCAR ack. Different category pairs, ERR_INVALID_STATE wins both.
> - boundary_precision_check: 2 — defects_found == Ac (2==2) accepts via inspection-lot DISPOSITION; open_finding_count==0 zero-edge closes via audit transition. Different metrics/endpoints.
> - cross_entity_state_dependency: 2 — AuditFinding→NCR (ERR_FINDING_NCR_OPEN); NCR→Deviation USE_AS_IS (success, cost 600). Different entity pairs.
> - resource_temporal_overlap: 2 — Deviation half-open exclusive overlap (ERR_DEVIATION_OVERLAP); Audit 24h inclusive-buffer double-booking (ERR_AUDITOR_DOUBLE_BOOKED). Different interval semantics/entities.
> - compensating_invariant: 2 — NCR open/void conserves ncrs_attributed (→100.00); SCAR open/cancel conserves open_scar_count (→100.00). Different conserved quantities.
> §1.5 gaps resolved via priority ladder: None. Formula literals all computed in Python against §1.3 constants. scaffold_lint.py clean.

§1.9 corner-design subagent summary (verbatim):
> Produced SCAFFOLD_CORNER_DESIGN.yaml (single top-level key scaffold_corner_design), walking all nine claim-extraction-guide sections.
> Per-section (full / stubs): entities 16/0, state_machines 23/6, calculations 6/5, validations 7/8, endpoints 4/0, errors 0/20, rbac 6/0, cross_cutting_layers 5/2, consistency_model 1/0. TOTAL 68 full / 41 stubs (109 instances, 9 sections).
> §1.8 overlap handled via excluded_because stubs citing exact <rule_id> / <instance_name>; errors section stubs all 20 error_ids to the firing instance. §1.5 gaps: none — all chains composed from existing endpoints; SCAFFOLD.yaml not modified. OCC expected_control_plan_version always captured from prior GET, never literal. One initial lint violation (system-fields test sent computed/system keys) fixed by sending only declared input. Lint verdict: clean lint.

## Step 3: Copy shared files — 2026-06-03T13:39:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0121_quality_management_system/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T13:45:40.000Z

Generated workspace/PRD.md (273 lines) from SCAFFOLD.yaml only; both design YAMLs and sibling tasks confirmed not read. Built incrementally to avoid stream-idle timeout.

Sections: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Props/Versioning, 2.5 Precision/Rounding/Monetary, 2.6 Nested Retrieval/Reverse Lookups, 2.7 OCC on Control Plans, 2.8 Cascading Side Effects/Derived-Field Reconciliation, 2.9 SoD/Resource Ownership, 2.10 Validation Precedence); §3 Business Logic (3.1 Actors/Suppliers/Catalogue → 3.10 Control-Plan Revisions/Test-Driving Clock); §4 Endpoint Definitions (47-row table); §5 Error Code Catalogue (20-row table).

Subagent self-reported hard-contract results (verbatim):
> Field coverage check: 81 required, 81 present, 0 missing — PASS
> Rule coverage check: 15/15 validations w/ ordering; 1/1 OCC rejection (expected_control_plan_version + ERR_STALE_VERSION/412, no race wording); all state-machine transitions (from/to + preconditions→error_id + side effects); 4/4 calculations reconstructible step-for-step; endpoints side_effects/applies_to expressed; sibling-branch symmetry equal density — PASS
> Path purity check (§3 only): 525 backtick tokens scanned, 0 path/method/method+path tokens — PASS
Coverage confirmation: all 13 entities (EightDStep noted id/created_at only), 8 state machines (cyclic + branching rendered symmetric density), 4 calculations (all constants embedded), 15 validations (precedence in §2.10), 47 endpoints, 20 errors, 5 roles (4 Personnel-backed + 1 Supplier-backed).

## Step 5: Generate unit tests — 2026-06-03T13:55:00.000Z

Launched concurrently with Step 6 (physical isolation: impl-gen could not see test_suite/). On disk: test_helpers/ = 9 files; test_suite/ = 8 files (conftest + 7 test files), ~104 test functions.

Subagent summary (verbatim):
> test_helpers/ — 9 files: __init__.py, types.py, api_client.py (one method per endpoint), api_errors.py (20 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (per-instance make_<role>_headers for all five entity-backed roles), fixtures.py (tiered composite helpers).
> test_suite/ — 8 files, 106 test functions (conftest + 7). Queue A (Difficulty) files 01–03: 36 tests. Queue B (Corner) files 04–07: 68 tests.
> Coverage (design-index-only, audited programmatically): Queue A §1.8 18/18 instances translated (≥2 tests each), 0 skipped. Queue B §1.9 68/68 non-stub instances translated (≥1 test each), 0 skipped; all 41 excluded_because stubs correctly NOT translated and every stub's difficulty_instance resolves to a real §1.8 instance.
> Skipped: none — every non-stub instance passed the PRD-first two-condition filter.
> Verification: every docstring ends with exactly one Design: line (0 untagged/dual/dangling); all 152 quoted PRD citations verify verbatim; no scaffold/§/Table-N leakage; no skip/skipif/xfail; helpers import cleanly; all 106 tests collect under pytest.

## Step 6: Generate implementation — 2026-06-03T13:55:00.000Z

On disk: workspace/implementation/ = 22 files (app.py, db.py, common.py, errors.py, response.py, middleware.py, requirements.txt, start.sh, routes/ ×10, services/ ×4). start.sh guards pip on `import flask`, exec foreground.

Subagent summary (verbatim):
> 47 route handlers matching 47 PRD §4 rows. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec python3 app.py; pip guarded on import flask. app.py pre-binds SO_REUSEADDR + 50-iter bind-retry loop then hands fd to werkzeug.make_server (survives same-port rapid-restart races, verified 5 restarts). Storage in-memory only (db.Store dicts); no SQLite/JSON/tmp; state wiped on restart (verified 404 after reboot). No startup seeding.
> Smoke-verified: auth 401/403, envelope shape, pagination; full NCR lifecycle; cost-of-quality branches (SCRAP=15000, REWORK=45000, USE_AS_IS=150 per-line-then-sum); supplier quality rating recompute + bands; AQL sampling code-letter + NORMAL→TIGHTENED at 2 consecutive rejects; audit 24h inclusive double-booking; audit-finding NCR flow + close gating; SCAR cascade to RESOLVED on NCR close; deviation overlap half-open + abutting allowed + in-use revoke block + expiry sweep on clock advance; CAPA effectiveness gates (prov ≥0.50, final ≥0.80) + cyclic rework loop; OCC ERR_STALE_VERSION 412 on stale control-plan version; validation precedence.
> One PRD/scaffold inconsistency handled: NCR-open precondition references Supplier status==ACTIVE, but Supplier entity has no status field / no deactivation path → resolvable supplier treated as always active (resolution-only check).

## Step 7: Run tests and iterate — 2026-06-03T14:15:25.000Z

Exited green. Final verification on disk: results.1–8.json all `passed == total == 105`. Long-lived fix subagent ran 3 total 8-round parallel sweeps (initial + 2). Known memory flakes (BadStatusLine keep-alive, same-port bind race) did NOT appear across 16 clean rounds.

Subagent summary (verbatim):
> **Iterations run:** 2 sweeps after the initial diagnostic sweep (3 total 8-round parallel sweeps). The first sweep surfaced exactly one failure, consistent across all 8 rounds (not flaky).
> **Tests deleted (1):**
> - `test_void_open_ncr_with_capa_blocked` (`test_suite/test_05_state_machines_breadth.py`) — **error-precedence-silence + unreachable-precondition collapse (STEP 1b)**. The test quotes PRD 3.2 ("an attempt to void an open report that already has a CAPA is rejected with `ERR_NCR_HAS_CAPA`") but that precondition is unreachable under the PRD's own state machine: PRD 3.4 requires an NCR to be `DISPOSITIONED` to open a CAPA, and opening the first CAPA immediately advances the NCR `DISPOSITIONED → CAPA_IN_PROGRESS`. So an NCR can never simultaneously be in `OPEN` status and have a CAPA. The test's own setup leaves the NCR in `CAPA_IN_PROGRESS` (its inline comment even says `# NCR now CAPA_IN_PROGRESS`), then asserts the OPEN-specific error. PRD 2.10 (Validation Precedence) deterministically settles this: the state check (`ERR_INVALID_STATE`, fired because no void transition is defined from `CAPA_IN_PROGRESS`) precedes the void operation's business rule (`ERR_NCR_HAS_CAPA`). The PRD thus uniquely determines the actual outcome to be `ERR_INVALID_STATE`, which is what the faithful implementation returns. Could not be salvaged as a test-helpers fix (STEP 2) because no PRD-faithful fixture sequence can construct an "OPEN NCR with a CAPA", and weakening the assertion to `ERR_INVALID_STATE` would be a downgrade toward the implementation (not permitted; the `validate_error_is_one_of` exception does not apply since the PRD names a specific, different error for an unreachable scenario).
> **Fixes applied to test_helpers/:** None.
> **Fixes applied to implementation/:** None — the implementation (`workspace/implementation/routes/ncr.py` `void_ncr`, returning `ERR_INVALID_STATE` for a `CAPA_IN_PROGRESS` void via the PRD 3.2 catch-all and PRD 2.10 precedence) was already PRD-faithful.
> **Final sweep:** Two consecutive 8-round parallel sweeps, every round `passed == total == 105`. No flakiness observed. Total test count after deletion: **105**.

## Step 8: Finalize PRD — 2026-06-03T14:19:18.000Z

Ran (not skipped: Step 7 had 1 deletion). Result: PRD_FINALIZED.md created, byte-identical to PRD.md (273 lines, 0 edits, verified `diff` empty).

Subagent summary (verbatim):
> PRD.md vs PRD_FINALIZED.md: 273 vs 273 lines — 0 lines changed, 0% delta. Zero edits.
> Why the single <step_7_diff> item required no PRD change: the Step 7 item was a test deletion (test_void_open_ncr_with_capa_blocked), not an impl fix or PRD mismatch. Verified against implementation/: CAPA opens only against DISPOSITIONED NCR (routes/capa.py:44-45); opening first CAPA advances NCR DISPOSITIONED→CAPA_IN_PROGRESS (routes/capa.py:63); NCR state machine monotonic — only OPEN writer is DRAFT→OPEN (routes/ncr.py:146), no path returns NCR to OPEN, so PRD 3.2 ERR_NCR_HAS_CAPA precondition (routes/ncr.py:232-236) is a dead branch; voiding CAPA_IN_PROGRESS falls through to catch-all ERR_INVALID_STATE (routes/ncr.py:254). PRD already uniquely determines the only reachable outcome (PRD 3.4 cascade + PRD 3.2 catch-all "Any transition attempted from a status that does not define it is rejected with ERR_INVALID_STATE" + PRD 2.10 precedence). No PRD silence, no mismatch → no edit per Method.
> Pre-edit search log: (a) subject = void_ncr OPEN→VOID transition + ERR_NCR_HAS_CAPA precondition + NCR-state reachability; (b) read routes/ncr.py void_ncr (all 3 branches) + open_ncr, routes/capa.py create_capa + transition_capa + _cascade_ncr_closed, grepped all status=OPEN assignments and all ERR_NCR_HAS_CAPA refs; (c) no wording adjustment — existing prose already consistent with every reachable path, no edit committed.

## Step 9: Complete PRD — 2026-06-03T14:27:57.000Z

Ran (always runs). PRD_COMPLETED.md created from PRD_FINALIZED.md via full impl scan: 273 lines, +4,548 chars, 18 in-place changes (36 diff lines), no sections/table rows added (headings 27→27, rows 71→71).

Subagent summary (verbatim):
> Counts: 14 ambiguity-pins, 4 mismatch-revisions. Line counts: PRD_FINALIZED 273 lines/49,211 chars; PRD_COMPLETED 273 lines/53,759 chars (+4,548).
> Per-change list:
> - §3.1 — revise — mismatch — email uniqueness NOT enforced; duplicate accepted — routes/personnel.py:28-36
> - §3.1 — revise — mismatch — supplier code uniqueness NOT enforced; duplicate accepted — routes/suppliers.py:21-43
> - §2.3 — insert — ambiguity — bad limit/offset → ERR_INVALID_REQUEST; list ties on equal created_at broken by ascending id — services/helpers.py:33-69
> - §3.2 — insert — ambiguity — supplier "ACTIVE" reduces to "resolves" (no status field); non-resolving at open → ERR_INVALID_STATE — routes/ncr.py:135-138
> - §3.2 — revise — mismatch — void authorizes both QE and QM; transition by state alone; no owner/SoD check on void — routes/ncr.py:218-254
> - §3.2 — revise — mismatch — for SUPPLIER only audit_finding_id forbidden (inspection_lot_id permitted); AUDIT/INTERNAL no extra omission — routes/ncr.py:60-68
> - §3.4 — insert — ambiguity — ADVANCE prerequisite-missing (D1/D2/D3, D4/D5+containment) → ERR_INVALID_STATE — routes/capa.py:144-164
> - §3.4 — insert — ambiguity — close D8-presence → ERR_INVALID_STATE, checked before SoD — routes/capa.py:194-200
> - §3.4 — insert — ambiguity — multiple D8 steps → final_effectiveness uses most-recently-created (created_at, id) — routes/capa.py:202-205
> - §3.4 — revise — mismatch — NCR-close cascade resolves EVERY matching ACCEPTED_RESPONSE SCAR, not just one — routes/capa.py:235-243
> - §3.5 — insert — ambiguity — SCAR transition: unknown action → ERR_INVALID_REQUEST; per-action role split → ERR_FORBIDDEN_ROLE; owner check after role+state — routes/scar.py:79-96
> - §3.5 — insert — ambiguity — SCAR create only FK-validates ncr_id/supplier_id; no SUPPLIER-source or supplier-match check — routes/scar.py:21-56
> - §3.6 — insert — ambiguity — defects_found init 0 at creation; sampling fields null until start — routes/inspection.py:97-108
> - §3.6 — insert — ambiguity — lot_size outside 2–500 clamped (below→A, above→H) before level shift — services/calculations.py:151-168
> - §3.6 — insert — ambiguity — unmapped (code letter A/B/C, or AQL 0.65/1.5/6.5 column) → start fails ERR_INVALID_REQUEST — services/calculations.py:171-202, app.py:57-61
> - §3.8 — insert — ambiguity — finding record/transition open to any Auditor (no lead-auditor ownership check) — routes/audit.py:117-206
> - §3.10 — insert — ambiguity — control-plan revision create evaluates OCC (ERR_STALE_VERSION) before sequence (ERR_REVISION_SEQUENCE) — routes/control_plan.py:73-78
> - §3.10 — insert — ambiguity — approval cascade order: supersede prior → stamp APPROVED → set current_revision_no → cascade needs_review — routes/control_plan.py:124-143
> - §2.4 — insert — ambiguity — every serializer emits its full declared field set; unset optional fields present as explicit null, not omitted — services/serializers.py (all)
> Note: Step-7-weakened test suite used auxiliarily only; it does not assert uniqueness conflicts, role-per-state void restrictions, or list tie-break order — consistent with implementation being authority for those pins.

## Pipeline complete — 2026-06-03T14:27:57.000Z

All 9 steps done. Final state: scaffold lint clean; 105 tests, two consecutive 8-round parallel sweeps fully green (105/105 × 16 rounds); PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (18 pins). Task artifacts complete.

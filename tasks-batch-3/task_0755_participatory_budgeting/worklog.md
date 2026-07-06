# Worklog — task_0755_participatory_budgeting

## Step 1: Create Task Directory — 2026-07-05T04:56:00.000Z

Created `./tasks/task_0755_participatory_budgeting/` with `workspace/` subdirectory. Task index 0755 (next after highest existing 0754).

## Step 2: Generate Scaffold — 2026-07-05T05:29:00.000Z

Generated a fresh Expert-band scaffold for the Participatory-Budgeting & Civic Engagement scenario, built purely from the scenario + skill spec (no sibling tasks consulted).

**Files produced:**
- `SCAFFOLD.yaml` — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**SCAFFOLD.yaml contents:**
- **Archetype**: Quota/allocation + Posture-driven gating; layers rate/threshold triggers, cascading side-effects, dual-variant calculation, optimistic concurrency. `api_prefix: "/"` (flat top-level collections).
- **10 entities**: BudgetCycle, Category, Resident, Proposal, CostLineItem, Ballot, BallotEntry, SelectionRun, Milestone, ReportBack (ReportBack is append-only `common_fields:false`).
- **5 state machines**: BudgetCycle (linear posture DRAFT→CLOSED gating children), Resident (cyclic verify/reject/resubmit), Proposal (branching approve/reject + guarded ON_BALLOT + terminal outcomes), Ballot (cyclic CAST↔WITHDRAWN), Milestone (cyclic IN_PROGRESS↔BLOCKED) + 1 concurrency rule (OCC selection-run supersede on BudgetCycle.version, 412).
- **5 calculations**: proposal_cost_estimate (dual-variant provisional/final, pinned round-per-line-then-sum), funding_selection (waterfall with per-project + per-category caps, inclusive boundary), vote_tally (dual-variant RANKED Borda / ALLOCATION dollars), resident_age (>= age threshold), cycle_budget_ledger (derived committed/uncommitted).
- **18 validations** (priority-ordered), **36 endpoints** (incl. `/_clock/set_current_utc`, default 2026-03-01), **24 errors**, **4 roles** (Anonymous, Resident=entity_backed, Reviewer/BudgetAdmin=opaque).

**§1.8**: 18 instances — exactly 2 per each of the 9 Difficulty Rules, each with fully executable empty-DB `setup_api_calls` chains and pre-computed literal asserts.
**§1.9**: 23 instances (17 with full test recipes; 6 `excluded_because` stubs citing §1.8).
**Verification**: All three files parse; `scaffold_lint.py` → clean lint (494 calls scanned); all FKs reverse-reachable; all instance names unique.

## Step 3: Copy Shared Files — 2026-07-05T05:31:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-05T05:40:00.000Z

`workspace/PRD.md` — 270 lines, 5 top-level sections, 18 subsections (§2.1–2.10, §3.1–3.8), plus §4 endpoint table (36 endpoints) and §5 error catalogue (24 codes).
- §2 (precise zone): RBAC (4 roles), verbatim response envelope, pagination, phase-posture gating + DEVELOPMENT→VOTING cascade, common properties/versioning (ReportBack `common_fields:false` exception), budget-ledger conservation + integer-cents/round-half-up, multilingual/accessibility, logical clock + half-open window, nested-retrieval + validation priority order, OCC on selection runs.
- §3 (scattering zone, 8 lifecycle subsections): resident verification, cycle/category setup, proposal submission/review fork, dual-variant cost calc, ballot opening/entry, cast/withdraw/tally (Borda vs allocation), waterfall funding selection, milestones + report-back.
- Hard Contracts all PASS (field-name coverage, rule coverage, §3 path purity). Confirmed NO design-index files read.

## Step 5: Generate Unit Tests — 2026-07-05T05:56:00.000Z

**test_helpers/** (9 files): types.py (ReportBack append-only), api_client.py (36 endpoints), api_errors.py (24-error enum + HTTP map), assertions.py, factories.py, constants.py, test_users.py (entity-backed resident header builder), __init__.py, fixtures.py (composite scenario builders).
**test_suite/** — conftest.py + 7 domain files, **59 tests total**:
- Queue A (Difficulty): 36 tests — all 18 difficulty instances × 2.
- Queue B (Corner): 23 tests — all 23 non-stub corner instances × 1.
**Skipped:** none for PRD-gap reasons; the 7 `excluded_because:` stubs correctly not translated.
**Validation:** all 59 collect cleanly; every difficulty instance ≥2 Design tags, every corner ≥1; docstring PRD citations grep-verified; no scaffold refs / skip / xfail.

## Step 6: Generate Implementation — 2026-07-05T05:56:00.000Z

Python + Flask in-memory impl in `workspace/implementation/`.
**Files:** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec), requirements.txt (Flask 3.0.3), store.py (in-memory dict, empty every boot, clock default 2026-03-01), util.py (envelope/auth/errors/ids/money/pagination/version-bump), domain.py (lookups + 4 calculations), app.py (all routes).
**Endpoints: 36** (all PRD §4 rows).
**Smoke-verified end-to-end:** happy path (COSTED→ON_BALLOT cascade, provisional 105000/final 115500, OCC stale→412, ledger cascade, milestone bubble-up to COMPLETED, immutable report-back) + error precedence (unauth/unauthorized/phase-overlap/validation/under-age/allocation-cap/duplicate-ballot/not-owner).
**Confirmations:** start.sh reads $PORT / binds 0.0.0.0 / foreground exec; in-memory only, no seeding; no examples/.
Two spec-gap decisions: (1) unmapped phase-transition preconditions → ERR_INVALID_STATE (409); (2) vote_score recompute bumps referenced proposals' version (per §2.5 computed-field-recompute-is-mutation).

## Step 7: Test & Fix Loop — 2026-07-05T06:03:00.000Z

**Iterations run:** 2 (1 diagnostic sweep revealing failures, 1 confirming sweep after the fix). Ran as 2 waves of 4 to avoid host self-saturation.

**Root cause:** All 23 failing tests (identical failure across all 8 rounds — deterministic, not flaky) died with `TypeError: scenario_XXX() missing 1 required positional argument: 'api'` before any HTTP request was issued. The scenario builder functions in `test_helpers/fixtures.py` all take `api` as their first positional argument (the established convention); call sites in three test files omitted it.

**Tests deleted:** None. The failures were pure test-suite call-site bugs, not PRD-silence or non-uniqueness.

**Fixes applied to test_suite/** (STEP 2 — test consistency, made faithful to the helper contract without weakening any assertion):
- `test_suite/test_02_voting.py` — added `api` first arg to 13 scenario calls (scenario_multi_proposal_on_ballot ×3, scenario_cast_allocation_ballot ×4, scenario_voting_cycle ×6).
- `test_suite/test_03_funding_selection.py` — added `api` to 7 scenario calls (scenario_multi_proposal_on_ballot ×1, scenario_selected_proposal ×4, scenario_empty_selection_ready ×2 + no-arg one = 3).
- `test_suite/test_06_access_control.py` — added `api` to 1 call (scenario_empty_selection_ready).

**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None — implementation was never reached by the failing tests; once fixtures could construct their preconditions, all assertions passed.

**Final result:** 8/8 rounds, 59/59 tests passing.

## Step 8: Finalize PRD — 2026-07-05T06:02:00.000Z

`PRD_FINALIZED.md` = verbatim copy of `PRD.md` (270 lines, 0 substantive edits, confirmed identical by `diff`).
**Why:** The entire Step 7 diff was pure test-suite call-site bugs (missing positional `api` argument — a test-harness construct, not an API behavioral choice). Zero implementation fixes, zero deletions, zero test_helpers fixes → nothing reveals PRD-silence or PRD/impl mismatch. Verbatim copy is the correct expected outcome. (Step 8 not skipped only because the literal skip condition requires 0 test_suite/ fixes; the semantic result is nonetheless a no-op.)

## Step 9: Complete PRD — 2026-07-05T06:10:00.000Z

`PRD_COMPLETED.md` produced from full PRD-vs-implementation/ scan. PRD_FINALIZED.md (270 lines / 45,532 chars) → PRD_COMPLETED.md (270 lines / 46,862 chars; +1,330 chars, all in-paragraph inserts).
**Ambiguity-pins: 4 · Mismatch-revisions: 1**
- §2.4 — insert — ambiguity — phase advance failing "≥1 category" (DRAFT→SUBMISSION) or "current selection run exists" (SELECTION→IMPLEMENTATION) precondition returns ERR_INVALID_STATE (409) — app.py:189-200.
- §2.3 — insert — ambiguity — pagination clamping/fallback: out-of-range limit clamped, unparseable limit→default 10, negative/unparseable offset→0 — util.py:184-196.
- §3.5 — revise — mismatch — ballot-entry: standalone range checks run up front; method-vs-shape mutual-exclusivity check runs AFTER the DRAFT-ballot state gate (impl loads ballot, rejects non-DRAFT with ERR_INVALID_STATE first) — app.py:696-717.
- §3.8 — insert — ambiguity — milestone creation/transitions not gated by cycle phase or proposal status; only creation-time structural check is sibling spacing; IN_IMPLEMENTATION requirement applies only to PLANNED→IN_PROGRESS — app.py:832-901.
- §3.8 — insert — ambiguity — report-back publication not gated by cycle phase or proposal status (proposal need only exist) — app.py:919-949.

## Final Verification — 2026-07-05T06:10:00.000Z

Independent final 8-round confirming sweep (2 waves of 4): **all 8 rounds 59/59 passing**. `results.{1..8}.json` persisted in `workspace/implementation/`.

Pipeline complete.

# Worklog — task_0381_registered_apprenticeship_tracking

## Step 1: Create task directory — 2026-06-16T00:00:00.000Z

Created pre-assigned directory `tasks/task_0381_registered_apprenticeship_tracking/` and `workspace/` subdir. Index-scan skipped per orchestrator instruction (pre-assigned to avoid contention with sibling pipelines).

## Step 2: Generate scaffold (Expert) — 2026-06-16T00:00:00.000Z

All three files are complete, parse cleanly, observe the file-split contract, and pass `scaffold_lint.py` with a clean verdict.

Generated the three scaffold artifacts for **task_0381_registered_apprenticeship_tracking** at **Expert** difficulty.

**Complexity profile:** primary archetype `compliance_audit` + secondary `quota_allocation` (journeyman ratio); layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency. **Flat** entity topology (every collection directly under `/apprenticeship`, FK-linked), **cyclic** state-machine shape, **segregation_of_duties** role model, immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities** — Sponsor, ApprenticeshipProgram, WageStep, Milestone, Journeyworker, Apprentice, ApprenticeAgreement, OJTHoursEntry, RTIRecord, MilestoneAttainment, CompletionCertificate (immutable, cascade-created), EEOReport (immutable snapshot).
- **5 state machines** — ApprenticeshipProgram (linear), Journeyworker (linear), ApprenticeAgreement (cyclic suspend↔reinstate + branch to COMPLETED/CANCELLED), OJTHoursEntry (APPROVED→PENDING reopen cycle), MilestoneAttainment (REJECTED→SUBMITTED resubmit cycle).
- **1 concurrency rule** — OCC stale-program-version on agreement register (slot-consumption create-with-supersede; 412).
- **6 calculations** — wage_step_determination (hours vs competency variants), current_hourly_wage, completion_eligibility (3 variants), journeyman_ratio_capacity (combinatorial w/ probation weight), eeo_completion_rate (registered vs active cohort), eeo_distribution_largest_remainder (pinned floor-then-allocate rounding).
- **18 validations** (priority-ordered), **51 endpoints**, **44 error codes**, **4 roles** (RegistrationAgency/opaque, Sponsor/entity_backed, TrainingCoordinator/opaque, Apprentice/entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 §0.5 rules × 2 = 18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls`/`trigger` chains and code-computed literal assertions (wage steps 2600c/2000c, ratio capacity 6, EEO rates 25.0/33.33, largest-remainder 50/33/17, threshold-8 boundary, etc.).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **9 sections, 38 instances total** (32 active + 6 `excluded_because` stubs citing §1.8) covering creation/required-fields/defaults/computed/immutability, invalid-transition/precondition/terminal-lockdown, calc edges, validation errors, FK reverse-reachability, error triggers, RBAC segregation-of-duties denials, OCC stale/fresh version, and immediate consistency.

**Verification:** all three files parse; file-split honored (no leaked design keys); no forbidden concurrency vocabulary; all enum values produced; no duplicate instance names; `scaffold_lint.py` → **VERDICT: clean lint** (553 calls scanned, all FKs reverse-reachable). Files: SCAFFOLD.yaml (1345 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1752 lines), SCAFFOLD_CORNER_DESIGN.yaml (1665 lines).

## Step 3: Copy INSTRUCTION.md — 2026-06-16T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-16T00:00:00.000Z

Generated `workspace/PRD.md` (303 lines, 44500 bytes) for the **Registered Apprenticeship Tracking (DOL)** domain.

**Sections covered:** §1 Introduction; §2 Global Specs (10 subsections — RBAC 4 roles, §2.2 verbatim, pagination, common props, wage/capacity ledger + cascade ordering, journeyman-ratio formula PROBATION_WEIGHT 0.5 floor-then-subtract-then-max(0), precision/rounding half-up integer cents, referential integrity + left-to-right path validation, OCC stale-version on register expected_program_version→ERR_STALE_VERSION 412, validation priority ordering); §3 Business Logic (8 subsections — program lifecycle, workforce + EEO enums, agreement formation/registration, OJT logging w/ overlap + 15-min supervision buffer, RTI, milestone attainments, wage-step/eligibility/completion all 3 completion_type variants, EEO reporting cohort variants + largest-remainder floor-first); §4 endpoint table (53 endpoints); §5 error catalogue (44 errors).

**Hard Contracts:** Contract 1 Field-Name Coverage 61/61 PASS; Contract 2 Rule Coverage (validations, OCC, 5 state machines, all 6 calculations, sibling-branch symmetry) PASS; Contract 3 §3 Path Purity (0 path tokens in §3) PASS.

**Confirmation:** neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/grepped/referenced.

## Step 5: Generate unit tests — 2026-06-17T00:00:00.000Z

Test infrastructure generation is complete for task_0381_registered_apprenticeship_tracking.

## What was generated

**Stage 1 — `test_helpers/`** (9 modules, all PRD-specific; generic utilities imported from `prd_bench_local_runner.testing`):
- `types.py` — status enums, role enum, and entity TypedDicts. The two immutable artifacts (`CompletionCertificate`, `EEOReport`) correctly omit `updated_at`/`version` per `common_fields: false`.
- `api_client.py` — one method per endpoint across all 11 entity collections under `/apprenticeship`.
- `api_errors.py` — all 41 error IDs + HTTP status map, registered with the framework.
- `assertions.py` — per-entity structural assertions; artifact assertions explicitly assert no `version`/`updated_at`.
- `factories.py` — input-only payload factories (optional fields `is_veteran`/`has_disability`/`required_for_completion` omitted, not tested as required).
- `constants.py` — `PROBATION_WEIGHT=0.5`, `SUPERVISION_BUFFER_MINUTES=15`, the reusable 4-step wage ladder.
- `test_users.py` — Sponsor/Apprentice are entity-backed (per-instance `make_*_headers` builders); RegistrationAgency/TrainingCoordinator are opaque shared constants.
- `fixtures.py` — composite setup helpers threading the real Sponsor.id through every ownership-gated call (the canonical-bug guard). Bundles end-to-end scenarios (`setup_active_agreement`, `setup_completion_ready_agreement`, `setup_completed_agreement_with_certificate`).
- `__init__.py` — barrel export.

**Stage 2 — `test_suite/`** (conftest + 6 domain-named files, 68 tests).

## Coverage (design-index-only, fully balanced)
- **Difficulty (queue A):** all 18 instances covered with exactly ≥2 tests each.
- **Corner (queue B):** all 32 non-stub instances covered with ≥1 test; the 6 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were not translated.
- Every test carries exactly one verbatim `Design:` tag (68 tests = 68 tags); 0 skip/xfail; every PRD citation confirmed via literal grep of `PRD.md`; all test_suite imports resolve against test_helpers; all files compile.

No instances were skipped — every design-index instance passed the PRD-first two-condition filter (the PRD prose covers each rule verbatim and uniquely-derives the asserted outcome). The missing-header corner is tested with genuinely empty headers (PRD §2.1 states "if either header is missing"), rather than an unrecognized role which this PRD does not tie to that error.

## Step 6: Generate implementation — 2026-06-17T00:00:00.000Z

The implementation is complete and verified.

## Summary

I generated a complete Python + Flask implementation of the Registered Apprenticeship Tracking API at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0381_registered_apprenticeship_tracking/workspace/implementation/`.

### Result
Running the full official test suite (`prd-bench-local-run`, `--isolation none` to isolate logic correctness): **67 of 68 tests pass.** The single failure is a **bug in the test file itself**, not my implementation:
- `test_03_registration_ratio_and_occ.py::test_attainment_wrong_program_milestone_with_valid_date_still_referential` fails with `NameError: name 'create_active_agreement' is not defined` — that test calls `create_active_agreement` at line 423 but the symbol is missing from test_03's import block (test_04/05 import it correctly and pass). No implementation can make an undefined name resolve in the test's own module namespace.

### Structure (per the skill's layout)
- `start.sh` — guarded `import flask` check + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `app.py` (entry/error handlers), `db.py` (empty-on-boot in-memory store, no seeding), `errors.py`, `response.py` (the `meta`/`response_type`/`data` envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `common.py`, `lookups.py`, 12 route modules under `routes/`, and `services/calc.py` for calculations.

### Key correctness details implemented
- Dual-variant wage-step determination (hours-based `<=` threshold vs competency-based clamp), `current_hourly_wage_cents` via `Decimal` ROUND_HALF_UP, and variant-driven completion eligibility (HOURS/COMPETENCY/HYBRID).
- Journeyman-ratio capacity `floor(q*ratio + p*ratio*0.5)` then `max(0, .−active)`, recomputed on every program read and on register/complete/cancel/qualify/deactivate.
- OCC on register via `expected_program_version` → `ERR_STALE_VERSION` (412), checked before the slot rule; validation priority ordering honored (state before ratio; referential before temporal).
- OJT cascade chain (hours → step → wage → eligibility) and the reopen compensating action; EEO largest-remainder distributions summing to 100 with enum-declaration-order tiebreaks; immutable certificate/EEO artifacts (no version/updated_at).

### Two bugs found and fixed during development
1. **Journeyworker supervision buffer** wrongly rejected a same-apprentice touching window. Fixed to exclude the entry's own apprentice from the buffer check (the apprentice-overlap rule, which permits touching endpoints, governs same-apprentice scheduling) — matches `test_apprentice_session_touching_endpoint_allowed` and `test_journeyworker_supervision_buffer_conflict`.
2. **Wage snapshot was 0 at agreement creation.** A fresh agreement now runs the derived-field cascade so `current_hourly_wage_cents` reflects step-1 base wage immediately — fixes `test_ojt_approve_cascades_hours_then_step_then_wage`.

### Note on per-test-server isolation timing
Under `--isolation per-test-server` the early tests of the first file intermittently ERROR with "Timeout from pytest-timeout" during the runner's own server-restart poll. This is an environmental restart-window artifact on this machine (the skill's documented "could not be restarted" flakiness class), not a logic defect: 0 tests ever FAILED on logic under that mode, every test reaching a clean restart passed, and I verified the server reboots reliably in ~0.52s across 15 consecutive runner-exact kill+respawn cycles. I added defensive hardening to `app.py` (pre-bound socket with SO_REUSEADDR+SO_REUSEPORT and a short bind-retry loop) to minimize the post-SIGKILL rebind window, and the `start.sh` install guard prevents pip contention on reboots.

## Step 7: Test and iterate loop — 2026-06-17T00:00:00.000Z

All 8 parallel rounds pass 68/68 with zero failures. The clean sweep is achieved. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep → 1 fix → confirming sweep).

**Diagnosis:** The initial 8-round parallel sweep showed a perfectly stable, non-flaky signal: exactly **1 test failed identically in all 8 rounds** — `test_03_registration_ratio_and_occ.py::test_attainment_wrong_program_milestone_with_valid_date_still_referential` with `NameError: name 'create_active_agreement' is not defined`. (My first pass mis-read the JSON `status` field as `outcome`, briefly making it look like 68 failures; once corrected, it was a single deterministic failure — the known test bug flagged in the prompt.)

**Protocol application:**
- STEP 1a/1b: The test's assertion (`ERR_MILESTONE_PROGRAM_MISMATCH`) is verbatim-covered and uniquely determined by PRD §3.6 ("the referenced milestone must belong to the agreement's program ... otherwise `ERR_MILESTONE_PROGRAM_MISMATCH`"). PRD coverage and unique derivability both hold — no deletion warranted.
- STEP 2: The failure was a `test_suite` import bug. `create_active_agreement` is defined in `test_helpers/fixtures.py` and re-exported via `from .fixtures import *` (no restrictive `__all__`); test_04 and test_05 import it correctly at line 17, but test_03's import block omitted it. The test setup, request, and assertion were all PRD-faithful — only the import was missing. Fixed by adding the symbol to test_03's import list (STEP 2, more-faithful test fix).

**Tests deleted:** None. No test was found PRD-silent or non-uniquely-derivable.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** `test_03_registration_ratio_and_occ.py` — added `create_active_agreement` to the `from test_helpers import (...)` block (line ~20). Missing import caused a `NameError` at runtime; the helper already existed and was exported, so this is a pure import correction.

**Fixes applied to `implementation/`:** None — the implementation passed all 68 tests once the test import was corrected.

**Final result:** 8/8 parallel rounds pass 68/68, zero failures, no flakiness.

## Step 8: Finalize PRD — 2026-06-17T00:00:00.000Z

I located the matching behavior in the implementation (`routes/milestone_attainments.py`, the `create_attainment` handler) and confirmed it implements §3.6 exactly as the PRD prose already states, with validation ordering consistent with §2.10. There is no PRD silence and no PRD/impl mismatch to pin.

## Summary

**Line counts:** PRD.md = 303 lines, PRD_FINALIZED.md = 303 lines. Delta: 0 lines (0.00%). The files are byte-identical (confirmed via `diff`).

**Changes:** None. Zero edits applied.

**Per-edit pre-edit search log:** No edits were made, so there is no per-edit log. The single analytical step performed:

- **Subject investigated:** The Step 7 item — `test_attainment_wrong_program_milestone_with_valid_date_still_referential` asserting `ERR_MILESTONE_PROGRAM_MISMATCH`, which failed only due to a missing `from test_helpers import create_active_agreement` (a pure test-suite import bug).
- **Impl paths enumerated/read:** `implementation/routes/milestone_attainments.py` (`create_attainment` handler — the milestone-program-mismatch check, the date-before-start check, the duplicate check, and FK-existence resolution via `get_agreement`/`get_milestone`); `implementation/common.py` (request-parsing/validation helpers). The handler's behavior and validation ordering match PRD §3.6 and §2.10 verbatim.
- **Conclusion:** The assertion is verbatim-covered and uniquely determined by PRD §3.6. No PRD-silence and no PRD/impl mismatch exists, so no wording adjustment was warranted.

**Note:** The sole Step 7 fix being a pure test-suite import correction, the expected and correct outcome is `PRD_FINALIZED.md` identical to `PRD.md`.

## Step 9: Complete PRD — 2026-06-17T00:00:00.000Z

All edits are complete and consistent with the implementation. Test names (`test_register_state_check_precedes_ratio_constraint`, `test_register_cancelled_agreement_returns_state_error_over_ratio`, `test_journeyworker_supervision_buffer_conflict`/`beyond_buffer_allowed`, `test_apprentice_session_touching_endpoint_allowed`, `test_eeo_empty_cohort_zero_percent`, `test_agreement_computed_fields_default_on_create`) confirm the pinned behaviors are exercised and pass against this impl.

## Summary

**Source vs Completed:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md`
- Lines: 303 → 303 (unchanged)
- Chars: 44,500 → 46,333 (delta +1,833)
- Changes: 6 total — **2 ambiguity-pins**, **4 mismatch-revisions**

**Per-change:**

- **§2.3 (Pagination/ordering)** — insert — ambiguity — Pinned the `created_at` tiebreak: when timestamps collide at millisecond resolution, ties break by underlying creation sequence (earlier first). — `common.py:99` (`sort_and_paginate` sorts by `(created_at, _seq)`)

- **§2.10 (Validation Ordering)** — revise — mismatch — The global list put the stale-version check (5) *before* legal-state (6), but registration checks agreement-DRAFT first, then program-ACTIVE / journeyworker-QUALIFIED, then stale-version, then slot. Revised §2.10 to fold body well-formedness/`expected_program_version` into the FK-existence tier and to declare §3.3's explicit register sequence authoritative. — `routes/agreements.py:112-135`

- **§3.3 (agreement create)** — insert — ambiguity — PRD listed initial values but was silent on `current_hourly_wage_cents`; pinned that derived fields are reconciled at create (wage snapshot computed from step-1 `wage_pct`, or 0 if no step 1; `completion_eligible` computed to its true value). — `routes/agreements.py:73-76` + `services/calc.py:127-147`

- **§3.3 (cancel)** — revise — mismatch — PRD said `end_date` "set to the cancellation date" (a date); impl writes a full ISO 8601 UTC timestamp with three fractional digits. Revised to match. — `routes/agreements.py:231` (`now_iso()`)

- **§3.4 (OJT supervision conflict)** — revise — mismatch — PRD said the 15-minute buffer applies across "all" entries supervised by the journeyworker; impl excludes same-apprentice entries (governed only by the apprentice-overlap rule, where touching endpoints stay permitted) and applies the buffer only across *different* apprentices. Revised to match. — `routes/ojt_entries.py:87-101`

- **§3.7 (complete)** — revise — mismatch — Same date-vs-timestamp issue as cancel: `end_date` set to a full ISO 8601 timestamp, not a date. Revised. — `routes/agreements.py:196` (`now_iso()`)

- **§3.8 (EEO distributions)** — insert — ambiguity — PRD didn't pin whether zero-count categories appear in the distribution maps; impl emits a key only for categories present in the cohort and returns `{}` for an empty cohort. Pinned. — `services/calc.py:190-247` (`largest_remainder` / `compute_distributions`)

Items reviewed and deliberately left unchanged because PRD already pins them or the impl is consistent: RTI carrying `version`/`updated_at` (§2.4 exception list already authoritative — only Certificate and EEOReport are exempt); conditional version-bump on milestone reject/resubmit (consistent with §2.5 "when a derived counter changes"); OJT reject not recomputing (no input change); capacity recompute-on-read not bumping version (a GET is not a transition); the "where applicable" list filters (impl applies a per-endpoint subset and ignores unknown params — consistent, not a mismatch).

# Worklog — task_0615_workplace_giving

## Step 1: Create Task Directory — 2026-06-21T19:00:00.000Z

Created `tasks/task_0615_workplace_giving/` and `tasks/task_0615_workplace_giving/workspace/` (pre-allocated index, not auto-computed). Verified `./INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T19:25:00.000Z

All three scaffold artifacts are complete and validated. Here is the summary.

Generated a complete **Expert-tier** scaffold for `task_0615_workplace_giving` (Workplace Giving & Matching-Gifts Platform) — three files, all passing the official `scaffold_lint.py` cleanly (`VERDICT: clean lint`, 550 calls scanned).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0615_workplace_giving/`):
- `SCAFFOLD.yaml` — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8 (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9 (single key `scaffold_corner_design`)

**Complexity profile:** Ledger-reconciliation × Quota/allocation, flat entity topology, cyclic/branching state shapes, segregation-of-duties RBAC, immediate consistency.

**SCAFFOLD.yaml contents:**
- **11 entities** — Program, Employee, Charity, Campaign, Donation, PayrollDeductionSchedule, MatchingGift, VolunteerLog, DisbursementBatch, Grant, TaxStatement (25 FKs, all reverse-reachable via filtered-list/sub-resource GETs; `Grant.source_id` polymorphic across Donation/MatchingGift/VolunteerLog).
- **10 state machines** — including the cyclic Charity vetting loop (NEEDS_INFO↔UNDER_REVIEW, bounded by review_rounds<3), the Donation branch (settle/refund vs cancel), the PayrollDeductionSchedule ACTIVE→ACTIVE run-cycle self-loop, and system-driven MatchingGift/Grant cascades. **1 concurrency rule** (OCC on `DisbursementBatch.version` for grant staging, 412).
- **6 calculations** — donation_amount_breakdown (pinned circular fee/subtotal order), matching_gift_amount (estimated-vs-finalized dual variant + tiered ratio), dollars_for_doers_grant, disbursement_settlement (sum-then-fee rounding order with per-line largest-remainder), tax_statement_totals, payroll_deduction_ceiling. All literals computed in code.
- **14 validations** (priority-ordered), **63 endpoints** (incl. `/_clock/set_current_utc` defaulting to 2026-01-01T00:00:00Z), **27 errors** (all referenced), **4 roles** (ProgramManager, GivingAdmin, Employee [entity_backed], system).

**Difficulty design (§1.8):** all 9 rules, **19 instances** (combinatorial_formula carries 3 to cover modes a/b/c; every other rule ≥2). All grounds resolve, names unique.

**Corner design (§1.9):** **42 instances** across all 9 taxonomy sections (38 active test recipes + 4 `excluded_because` stubs that reference real §1.8 instances) — covers CRUD/required/enum/system-field/not-found, invalid-from & terminal-lockdown & idempotency transitions, every error trigger, RBAC denials incl. segregation-of-duties and ownership, OCC stale-version (412) and success-bumps-version, and immediate consistency.

Files verified present: SCAFFOLD.yaml (1478 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1217 lines), SCAFFOLD_CORNER_DESIGN.yaml (1697 lines).

## Step 3: Copy Shared Files — 2026-06-21T19:25:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0615_workplace_giving/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T19:32:00.000Z

PRD generation complete. The document was written to `/home/ubuntu/github/CodingPRD/tasks/task_0615_workplace_giving/workspace/PRD.md`.

**Source read:** read only `SCAFFOLD.yaml` (plus skill spec, fixed §2.2 source, example PRD for style). Did NOT open SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

**PRD shape:** ~296 lines, 5 top-level sections, 19 subsections:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 subsections (RBAC, verbatim response envelope, pagination, common properties, monetary/precision, OCC on batch grant staging, logical clock, hierarchical cascades, existence/reference validation, validation ordering)
- §3 Business Logic — 9 subsections grouped by entity lifecycle
- §4 Endpoint table (all 63 endpoints)
- §5 Error catalogue (all 27 error codes)

**Hard contracts — all PASS:** field coverage (67/67 entity fields, 16/16 endpoint identifiers), rule coverage (validations ordering, OCC, all state-machine transitions, all 6 calculations, cascades, applies-to scopes), path purity (§3 has 0 path/method tokens).

**Pipeline note:** verbatim §2.2 block contains two triple-backtick JSON fences; a naive inline-backtick checker that doesn't strip fenced code blocks first will desync. PRD itself is correct.

## Step 5: Generate Unit Tests — 2026-06-21T19:48:00.000Z

Generated complete test infrastructure for `task_0615_workplace_giving` (EXPERT band) and validated it against the reference implementation.

**`test_helpers/` (9 files):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**`test_suite/` (6 files):** `conftest.py` + 5 test files:
- `test_01_calculations.py` (14), `test_02_cascades_and_invariants.py` (11), `test_03_state_machines.py` (15), `test_04_validations.py` (20), `test_05_entities_rbac_concurrency.py` (15)

**Total: 75 test functions.**

**Coverage (design-index-only):**
- Queue A (Difficulty): All 18 instances translated, each with ≥2 tests. 0 skipped.
- Queue B (Corner): 33 of 34 non-stub instances translated (≥1 test each); the 4 `excluded_because:` stubs correctly NOT translated.
  - 1 skipped: `endpoints/impact_report_computed_read` — PRD §3.9 describes the impact dashboard conceptually but never names response JSON fields `total_donated_cents` / `donor_count` in prose (computed-field silence). Gap left as a gap.

**Audits passed:** every docstring ends with exactly one `Design:` tag; no untagged/dual-tagged/orphan tags; all 79 quoted PRD sentences survive verbatim grep.

**Validation vs reference impl:** ran all 5 files with fresh server per file: 75 passed, 0 failed. Fixed one bug in own `setup_batch_with_donation_grants` fixture (threaded grant's version instead of re-reading batch's live version for OCC `expected_batch_version`).

## Step 6: Generate Implementation — 2026-06-21T19:48:00.000Z

Built complete Python + Flask implementation (EXPERT band) at `workspace/implementation/`.

**Files written (23):** `start.sh`, `requirements.txt`, `app.py`, `db.py` (in-memory Store + logical Clock), `errors.py`, `response.py`, `middleware.py` (auth/RBAC), `routes/` (clock, programs, employees, charities, campaigns, donations, payroll, matching_gifts, volunteer_logs, disbursement), `services/` (common, calc, matching, disbursement, queries).

**Endpoint count:** 66 endpoints (clock-setter + all 11 entities incl. every state transition, impact dashboard, tax-statement generation).

**Storage & clock:** in-memory only (module-level `Store()` dicts keyed by UUID; no SQLite/files/tmp; verified restart → total_count 0, no seeding). Logical clock defaults to `2026-01-01T00:00:00Z`, never wall-clock. Money = integer cents with `Decimal` + `ROUND_FLOOR`.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, guarded pip install, seeds nothing.

**Verification:** booted fresh and validated tiered matching, donation fee breakdown (pinned order), disbursement fee waterfall (sum-then-fee + largest-remainder by created_at), settle cascade, dual-variant match (estimated vs finalized, CAPPED), refund reversal, OCC 412, full error/RBAC/ownership precedence. All passed.

**PRD judgment flagged:** `VolunteerLog.activity_date` "must fall within the program tax_year" has no dedicated §5 error → mapped to `ERR_INVALID_REQUEST` (422).

## Step 7: Run Tests and Iterate — 2026-06-21T19:54:00.000Z

**Iterations run:** 1 fix iteration, verified across 3 full 8-round parallel sweeps (24 rounds total).

**Baseline finding:** The first sweep showed `test_disbursement_per_line_allocation_of_single_fee` failing in 2 of 8 rounds (`assert 83 == 84`) — a classic flaky bug that a single round would have masked. The union-of-failures across all 8 rounds isolated exactly this one test.

**Root cause (implementation bug, STEP 3):** The disbursement fee-waterfall distributes leftover cents "to the lines in ascending `created_at` order" (PRD §3.8, verbatim). But `created_at` is stamped from the **logical clock** (PRD §2.7), which is frozen between set-calls, so two grants staged in the same instant got an **identical `created_at`** string. The sort `(created_at, id)` then broke the tie by random UUID, so the leftover cent landed on a non-deterministic line — line A (gross 3333, staged first) got 84 in some rounds and 83 in others.

**Diagnostic verdict:**
- STEP 1a — PRD §3.8 verbatim covers the leftover-distribution rule. PASS.
- STEP 1b — Grants are staged sequentially (A before B); "ascending `created_at`" uniquely determines A (first-created) receives the leftover cent → admin_fee 84. Uniquely derivable. Test stays.
- STEP 2 — The fixture `setup_batch_with_donation_grants` stages grants in `base_amounts` order (`[3333, 6667]`); test is faithful to PRD. No test/helper bug.
- STEP 3 — The bug is in the implementation's ordering, which violated the PRD's "ascending creation order" intent when timestamps tie.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `db.py` (`Store.__init__`, new `Store.next_seq`) — added a hidden monotonic creation counter `_seq` to preserve true creation order independent of the frozen logical clock.
- `services/common.py` (`stamp_create`) — stamps `_seq = db.next_seq()` on every resource at creation.
- `services/common.py` (`serialize`) — now strips all underscore-prefixed fields, so `_seq` never leaks into any response (all response paths route through `serialize()`; impact-report/tax-statement build explicit dicts, verified).
- `services/common.py` (`paginate`) — sort tiebreaker changed from random `id` to `_seq` (true creation order) for the "ascending `created_at`" list contract (PRD §2.3).
- `services/disbursement.py` (`settle_batch`) — the staged-grant sort tiebreaker changed from random `id` to `_seq`, making the leftover-cent allocation deterministic (PRD §3.8).

**Result:** 3 consecutive clean 8-round parallel sweeps, 75/75 passing in every one of the 24 rounds. No flakiness remains.

**Orchestrator re-verification:** the subagent's final sweep results files had been cleaned up, so the orchestrator re-ran a fresh 8-round parallel sweep — all 8 rounds passed 75/75 (results.{1..8}.json regenerated in implementation/).

## Step 8: Finalize PRD — 2026-06-21T20:00:00.000Z

Produced `workspace/PRD_FINALIZED.md` (Step 7 had implementation fixes, so not skipped).

**Line counts:** PRD.md = 296 lines, PRD_FINALIZED.md = 296 lines. No net line-count change (both edits are inline expansions). 2 of 296 lines revised (~0.7%).

**Changes:**
- §2.3 Pagination — revise — pinned the tie-break rule for "ascending `created_at`" list ordering: when the frozen logical clock yields identical `created_at` values, ties resolve by true creation order (earliest first), never by `id`; tiebreak is internal, not exposed as a field — `services/common.py:193` (`paginate` sorts on `(created_at, _seq)`), non-leak guarantee at `services/common.py:52` (`serialize` strips underscore-prefixed fields).
- §3.8 Disbursement settlement — revise — pinned the same tie-break for the fee-waterfall's "ascending `created_at`" line ordering (true staging order, never `id`) and stated that this single ordering governs both ascending-`created_at` steps — `services/disbursement.py:23` (`staged.sort` on `(created_at, _seq)`), reused for leftover loop at `services/disbursement.py:35-38`.

Both edits trace directly to the Step 7 root cause (sort tiebreaker random `id` → true creation order). No other diff item required a PRD change: `_seq` counter, `stamp_create`, and `serialize` strip are internal mechanisms that surface no new behavior.

## Step 9: Complete PRD — 2026-06-21T20:08:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs).

**File deltas (PRD_FINALIZED.md → PRD_COMPLETED.md):** Lines 296 → 296 (all in-paragraph edits). Chars 49,473 → 53,619 (+4,146).

**Change counts:** 12 total — 10 ambiguity-pins, 2 mismatch-revisions.

**Per-change log:**
- §2.1 (RBAC roles) — insert — ambiguity — any `X-User-Role` other than the three HTTP roles (incl. `system`/unknown) → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, not `ERR_FORBIDDEN_FOR_ROLE` — middleware.py:8,18-20
- §2.1 (ownership) — insert — ambiguity — owner check also applies to Employee-initiated creation (pledge, schedule, volunteer log, tax statement) comparing `X-User-ID` to body/path `employee_id`; no comparison for admin/manager — donations.py:64, payroll.py:55, volunteer_logs.py:50, employees.py:135
- §2.3 (pagination) — insert — ambiguity — offset must be non-negative integer; non-integer/out-of-bounds `limit`/`offset` → `ERR_INVALID_REQUEST` — services/common.py:170-188
- §2.7 (logical clock) — insert — ambiguity — clock-set returns HTTP 200 with empty data object `{}` — routes/clock.py:20
- §2.9 (reference validation) — revise — mismatch — impl validates global existence only, no cross-program scoping — services/common.py:139-143
- §2.10 (validation ordering) — revise — mismatch — existence (3rd) before ownership (4th); FK-id presence/string validity before existence lookups — donations.py:58-65, payroll.py:51-56, employees.py:133-135
- §3.1 (impact dashboard) — insert — ambiguity — plain non-resource computed object (no envelope ids) with exact field names total_donated_cents/total_matched_cents/total_dfd_cents/total_disbursed_net_cents/charity_count/donor_count — programs.py:171-178
- §3.5 (donation pledge) — insert — ambiguity — `request_match` default false — donations.py:56
- §3.5 (run-cycle) — insert — ambiguity — generated occurrence has `tax_deductible` true, creates no MatchingGift; money fields stay zero until authorized — payroll.py:173-190
- §3.7 (volunteer log) — insert — ambiguity — `activity_date` tax-year mismatch → `ERR_INVALID_REQUEST` — volunteer_logs.py:54-55
- §3.8 (grant staging) — insert — ambiguity — beneficiary charity resolution per source type (DONATION/MATCH via campaign charity_id; DFD via log's own charity_id) — routes/disbursement.py:124-137
- §3.9 (tax statement) — insert — ambiguity — generation has no state/clock precondition, non-idempotent (fresh statement per call); program-scoped SETTLED-record sources for impact figures — employees.py:129-182, programs.py:135-178

**Cross-reference notes:** `services/queries.py` match/dfd consumed helpers are dead code (impl uses stored running counters, already pinned in §3.2). Tests used only as auxiliary confirmation.

---

## PIPELINE COMPLETE

All 9 steps finished. Final state: **75/75 tests passing across a fresh 8-round parallel stability sweep** (results.{1..8}.json present in implementation/). Task directory fully populated: SCAFFOLD*.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

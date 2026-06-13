# Worklog — task_0270_martial_arts_dojo_management

## Step 1: Create task directory — 2026-06-09T17:57:16.000Z

Created `tasks/task_0270_martial_arts_dojo_management/` and `tasks/task_0270_martial_arts_dojo_management/workspace/`. Pre-allocated path used directly; no tasks/ rescan or index recomputation (5 tasks running in parallel).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-09T18:16:47.000Z

Generated all three scaffold artifacts for **task_0270_martial_arts_dojo_management** at **Expert** difficulty. All files pass `scaffold_lint.py` with `VERDICT: clean lint` (403 setup/trigger calls scanned across §1.8 + §1.9, all conforming to §1.5; every FK has reverse-reachability).

**Files written:** SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (scaffold_difficulty_design only), SCAFFOLD_CORNER_DESIGN.yaml (scaffold_corner_design only).

**Complexity profile:** posture-driven-gating × temporal-windowing; graph topology; parallel state-machine shape; peer_roles. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.

**Entities (14):** Program, BeltRank, Family, Member, Instructor, Enrollment, ClassSession, Attendance, PromotionTest, Contract, Invoice, PrivateLesson, TournamentRegistration, ProShopOrder.

**State machines (10):** Member (parallel account dimension: ACTIVE/FROZEN/SUSPENDED/WITHDRAWN with auto-suspend), Enrollment (with promotion self-loop + ON_HOLD), ClassSession, Attendance, PromotionTest (branching fork-join: SCHEDULED→{PASSED, PASSED_PENDING_SIGNOFF, FAILED}→signoff), Contract (cyclic billing loop ACTIVE→ACTIVE + PAST_DUE), Invoice, PrivateLesson, TournamentRegistration, ProShopOrder. Plus 2 concurrency_rules (OCC on Member.version for contract-create and enroll-create).

**Counts:** 7 calculations (family_discount_tier, recurring_tuition_charge, pro_shop_pricing, early_termination_buyout, testing_eligibility_score, tournament_division, private_lesson_charge — two with live/pinned dual variants and two opposing rounding orders), 19 validations (priority-ordered), 64 endpoints (incl. 1 /_clock/advance test-driving endpoint), 19 errors, 4 roles.

**Design instance counts:** §1.8 difficulty = 18 instances (all 9 rules × exactly 2). §1.9 corner = 44 instances (42 active + 2 excluded_because stubs). All formula-derived asserts precomputed as literals (buyout 50000 cap, pro-shop round-per-line 188 vs sum-then-round 189, tuition 9000/12000, readiness 50, private-lesson 9000).

## Step 3: Copy INSTRUCTION.md — 2026-06-09T18:16:47.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09T18:22:34.000Z

Generated PRD at `workspace/PRD.md` (283 lines). Did NOT read either withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml).

**Section structure:** §1 Introduction; §2 Global Specs (10 subsections: RBAC, API Response Structure, Pagination, Common Resource Properties, Belt Progression & Derived-Field Reconciliation, OCC, Monetary/Rounding, Pro-Shop Pricing Discipline, Nested Retrieval & Referential Integrity, Validation Order); §3 Business Logic & Workflows (8 subsections); §4 Endpoint Definitions (67 endpoints, 4-col table); §5 Error Code Catalogue (19 errors).

**Hard Contract results (all PASS):** Contract 1 Field-Name Coverage 73 identifiers 0 missing; Contract 2 Rule Coverage (OCC stale-version, validation priority ordering, promotion-test gate ordering, all calc formulas — family tiers, tuition rounding-on-discount, pro-shop round-per-line-then-sum, private-lesson sum-then-round, buyout pinned order 50%/50000-cent cap, readiness 40/60 weights, tournament division boundaries — all cascades, all 19 error IDs in §2/§3 narrative); Contract 3 §3 Path Purity (392 tokens, 0 paths/methods).

## Step 5: Generate unit tests — 2026-06-09T18:39:06.000Z

Generated test infrastructure translating exclusively from the two design indices.

**Test files (5 + conftest):** test_01_pricing_calculations.py, test_02_promotion_and_billing_lifecycle.py, test_03_cascades_and_compensation.py, test_04_gating_boundaries_and_overlap.py, test_05_crud_rbac_and_concurrency.py, conftest.py.

**Counts:** 78 tests total — 36 from queue A (Difficulty), 42 from queue B (Corner). Every Difficulty instance ≥2 tests; every non-stub Corner instance ≥1 test. All 78 docstrings carry exactly one `Design:` tag; every quoted citation grep-verifies verbatim against PRD.md.

**Instances skipped (1):** Difficulty/priority_pair_validation_conflict/state_vs_capacity_on_attendance — fails unique-derivability. Asserts checking into a CANCELLED-and-full class returns ERR_INVALID_STATE over ERR_CLASS_FULL. PRD §3.4 enumerates attendance-creation gates (waiver, member-active, program-mismatch, class-full, already-checked-in) with NO session-state gate; PRD §2.10 ERR_INVALID_STATE precedence scoped to "state-transition endpoints", but POST /dojo/attendances is a creation endpoint. Paired instance waiver_vs_balance_on_promotion_test IS covered (PRD §3.5 states gate order).

**Stubs (correctly not translated, 2):** Corner/state_machines/tournament_withdraw_cascade_from_contract and Corner/calculations/buyout_provisional_vs_final_divergence — both excluded_because stubs cross-referencing covered queue-A instances.

**test_helpers/ files (9):** __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. All 78 tests collect; identity threading uses per-instance make_<role>_headers(entity_id) for entity-backed roles (Member/Instructor/ChiefInstructor); FrontDesk uses shared opaque header.

## Step 6: Generate implementation — 2026-06-09T18:39:06.000Z

Generated Python + Flask implementation at `workspace/implementation/`.

**File list:** start.sh, requirements.txt (flask==3.0.3), app.py, db.py, errors.py, response.py, common.py, middleware.py, services/ (domain.py, access.py, serialize.py), routes/ (14 blueprints: programs, families, members, instructors, enrollments, class_sessions, attendances, promotion_tests, contracts, invoices, private_lessons, tournament_registrations, pro_shop_orders, clock).

**Storage:** In-memory only — one Python dict per entity collection inside a single DB instance in db.py, keyed by UUID. Logical clock backs overdue/tournament date gating. No SQLite, no JSON file, no disk persistence.

**start.sh:** set -euo pipefail, cd to own dir, installs deps only if `import flask` fails, then exec python3 app.py → app.run(host="0.0.0.0", port=int($PORT or 10000)) foreground.

**No seeding — confirmed** (per-test-server cycle simulated: boot total_count 0 → create → kill/relaunch → total_count back to 0).

**Design note:** POST /dojo/_clock/advance only moves the logical clock; DUE→OVERDUE transition performed per-invoice by mark-overdue (scaffold lists both as trigger with "or").

## Step 7: Run tests and iterate — 2026-06-09T18:51:19.000Z

Clean 8-round parallel sweep: all 8 rounds pass 78/78.

**Iterations run:** 1 fix batch, then 1 validation round + 1 full 8-round parallel sweep (all green).

**Root cause:** The initial sweep failed 28 unique tests deterministically (identical in all 8 rounds — not flaky). All were *setup* failures, not implementation logic errors. They clustered into three causes, all rooted in test fixtures issuing requests inconsistent with the PRD-faithful implementation.

**Tests deleted:** None. (No test asserted a scaffold-only or PRD-silent rule outright; one assertion was split out — see below.)

**Fixes applied to `test_helpers/` (`fixtures.py`):**
- `create_program` — added `with_entry_rank=True` default that lays down a single terminal entry rank (WHITE, order 0). PRD §3.1 mandates "Exactly one rank per program is the entry rank ... a fresh enrollment always starts there," and PRD §3.4 says enrollment initializes `current_rank_code` to the program's entry rank — so a rankless program is not enrollable. ~20 tests enrolled into bare `create_program()` programs and the PRD-faithful impl correctly rejected them.
- `create_program_with_simple_chain`, `create_program_single_terminal_rank`, `setup_member_at_rank_order` — pass `with_entry_rank=False` since they build their own belt chains (otherwise rank_order-0 collision).
- `setup_member_at_rank_order` — also set `test_fee_cents=0` so the successive promotion-test schedulings used to climb the chain never accrue a balance crossing the 10000-cent suspension threshold (PRD §3.3), which had been suspending the member mid-climb (`ERR_MEMBER_NOT_ACTIVE`).
- Added `run_billing_and_pay(contract_id, member_id)` helper — runs one billing cycle then settles the generated TUITION invoice, keeping the running balance below the suspension threshold so the contract stays ACTIVE across multiple runs (per PRD §3.3/§3.6).

**Fixes applied to `test_suite/`:**
- `test_02::test_self_loop_stays_active_then_fulfills` and `test_each_tuition_invoice_uses_pinned_discount`, `test_01::test_cap_applied_after_rate_multiply` and `test_buyout_raw_value_capped_not_truncated_early` — switched their multi-run billing loops to `run_billing_and_pay`. Under PRD §3.6, unpaid monthly invoices accumulate and cross the 10000-cent threshold, auto-suspending the member and flipping the contract to PAST_DUE (confirmed PRD-faithful by `test_pay_invoice_unsuspends_member`). The loop tests must keep the member paid up to stay ACTIVE.
- `test_05::test_duplicate_belt_rank_code_returns_duplicate` — pass `with_entry_rank=False` (it adds its own WHITE rank manually).
- `test_05::test_correct_member_version_on_enrollment_succeeds` — removed the assertion `m_after["version"] == member["version"] + 1` (STEP 1c partial-coverage split). Neither PRD §3.4 nor the SCAFFOLD enrollment side-effects list any member-version increment on enrollment; enrollment creates a separate Enrollment resource and does not mutate the Member. Kept the PRD-faithful assertion `enr["status"] == "ACTIVE"` (PRD §3.4: "A new enrollment is born `ACTIVE`").

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout; every failure traced to test fixtures constructing preconditions the PRD-faithful server correctly rejected.

## Step 8: Finalize PRD — 2026-06-09T18:54:15.000Z

Produced `workspace/PRD_FINALIZED.md` (Step 8 ran because Step 7 had non-zero test_suite/ and test_helpers/ fixes).

**Line counts:** PRD.md = 283 lines; PRD_FINALIZED.md = 283 lines; delta 0 lines (+0.0%). Single edit expanded one existing §3.4 paragraph line.

**Change:** §3.4 (Enrollment) — revise — Added two pins: (1) enrolling into a program with no belt rank flagged as its entry rank is rejected with ERR_INVALID_REQUEST (HTTP 400); (2) enrollment creates only the Enrollment resource and does not mutate the target member, so the member's `version` is unchanged. — implementation/routes/enrollments.py:42-44 (entry-rank check) and :23-61 (member never touched).

**Pre-edit search log:** Subjects — (i) error when a program lacks an entry rank during enrollment; (ii) whether enrollment mutates the member/bumps version. Impl paths enumerated: routes/enrollments.py:23-61 create_enrollment (only enrollment-creation site; raises ERR_INVALID_REQUEST when entry_rank_for_program returns None; reads member version for OCC only, never touch(member)/family recompute); services/domain.py:313-317 entry_rank_for_program (selects is_entry_rank==true, NOT rank_order==0); routes/programs.py:89-132 create_belt_rank (is_entry_rank client-supplied bool default false). Wording adjustment: "no belt rank flagged as its entry rank" (keyed on is_entry_rank flag, not rank_order); member version "unchanged by an enrollment" (loose non-mutation claim). All other step_7_diff items are pure test-fixture mechanics or behavior PRD already determines (suspension cascade §3.3/§3.6) — no PRD pin needed.

## Step 9: Complete PRD — 2026-06-09T18:59:04.000Z

Produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md via full PRD-vs-implementation scan.

**Line counts:** PRD_FINALIZED.md → PRD_COMPLETED.md: 283 → 283 lines (unchanged; all edits in-paragraph). Chars 46,743 → 48,713 (+1,970).

**Counts:** 6 changes — 5 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- §2.6 (OCC) — insert — ambiguity — absent/non-integer expected_<parent>_version rejected with ERR_INVALID_REQUEST (400) at structural-validity stage, before version comparison — services/access.py:44-52.
- §3.2 (Family Discount) — insert — ambiguity — locked_family_discount_pct and buyout quote live_discount_pct stored/returned as decimal fraction 0.0–1.0 (0.1, 0.15, 0.2, 0.0), not integer points — routes/contracts.py:68,127.
- §3.5 (Testing Eligibility) — insert — ambiguity — exact failed_gates string tokens and order: "attendance", "days_in_rank", "account_status", "waiver_signed", "outstanding_balance", "rank_terminal"; empty when eligible — services/domain.py:256-268.
- §3.8 (Invoices) — insert — ambiguity — system-generated invoice due_at equals created_at (clock instant of generation); OVERDUE-eligible only after clock advances strictly past that instant — services/domain.py:145-164.
- §3.8 (mark-overdue) — revise — mismatch — requires status DUE (else ERR_INVALID_STATE 409); when not yet past due_at it is a no-op succeeding 200 returning still-DUE invoice — routes/invoices.py:91-108.
- §3.8 (clock advance) — insert — ambiguity — response data is exactly {"current_utc": <ISO>}; advancing clock does not sweep invoices; overdue transitions happen only per-invoice via explicit mark-overdue — routes/clock.py:13-26, routes/invoices.py:91-108.

## Pipeline complete — 2026-06-09T18:59:04.000Z

All 9 steps done. Final state: 78 tests across 5 test files; 8/8 stability-sweep rounds pass 78/78. Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, workspace/implementation/ (Flask), test_suite/, test_helpers/.

# Worklog — task_0242_weight_management_nutrition_program

## Step 1: Create task directory — 2026-06-07T16:40:42.000Z

Created `tasks/task_0242_weight_management_nutrition_program/workspace` via `mkdir -p` (ID pre-allocated by orchestrator; no auto-increment scan). Verified `INSTRUCTION.md` and `skills/prd-bench-scaffold-generator/SKILL.md` exist.

## Step 2: Generate scaffold — 2026-06-07T16:40:42.000Z

Generated all three scaffold artifacts at **Expert** difficulty for `task_0242_weight_management_nutrition_program`, validated clean by `scaffold_lint.py` (`VERDICT: clean lint`).

**Files written** (all under `tasks/task_0242_weight_management_nutrition_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (1096 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (590 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (750 lines)

**Design profile**: workflow_orchestration + compliance_audit; **flat topology** under `/wm` (priority-0% topology per §0.3); parallel state-machine shape; peer_roles; layers = dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency.

**Scale (Expert per §0.4)**:
- **15 entities** (Program, PlanCatalogItem, Member, Coach, IntakeAssessment, Enrollment, Goal, Milestone, WeighIn, CoachAssignment, MessageThread, Message, Invoice, EligibilityDetermination, RxAuthorization)
- **66 endpoints**, **35 error codes**, **21 validations**, **5 RBAC roles** (ProgramAdmin, Clinician, BillingAgent opaque; Coach, Member entity_backed), **2 OCC concurrency rules** (both on Enrollment.version)
- **9 state machines** including 2 non-linear: IntakeAssessment (cyclic revision loop) and Enrollment (parallel `clinical_status × billing_status`)
- **11 calculations** including dual-variant pairs: scale vs lean-adjusted progress (Member domain) and provisional-full vs final-prorated invoice (Invoice domain)

**§1.8 index**: 9 Difficulty Rules × 2 = **18 instances**, all grounds resolve, all setup chains lint-clean.
**§1.9 index**: **33 active corner instances + 6 `excluded_because` stubs = 39** across entities/state_machines/calculations/validations/endpoints/rbac/cross_cutting_complexity_layers/consistency_model; all 6 stub `difficulty_instance` refs resolve to named §1.8 instances; all names unique across both files.

**Key calculations** (literals pre-computed and pinned in test recipes): BMI (95kg/170cm→32.9), eligibility composite score (min/max + tier branch; 95kg RX→51.6), invoice round-per-line-then-sum (6000+2500→8500), proration final variant (daily rate 200×unused days), goal/scale/lean progress (52.63 vs 63.16 divergence), graduation eligibility (≥3 counted weigh-ins + ACHIEVED primary goal), coach active-load conservation.

**Verifications passed**: clean lint (FK reverse-reachability for all 29 FKs, OCC `${var}` discipline, payload/role/capture conformance over 493 calls); all grounds references resolve; no forbidden concurrency vocabulary; no raw formulas in asserts; no id-based decisions; top-level key isolation correct; every error code triggerable; all three files parse as valid YAML.

## Step 3: Copy INSTRUCTION.md — 2026-06-07T17:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0242_weight_management_nutrition_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T17:06:00.000Z

**File written:** `workspace/PRD.md` (326 lines). Read only `SCAFFOLD.yaml` (plus skill reference files); did NOT open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

**Section structure:**
- §1. Introduction — clinical-vs-billing dual pathway, deterministic clock, hard problems.
- §2. Global Specifications (9 subsections): 2.1 RBAC (5 roles; Coach/Member entity-backed, ProgramAdmin/Clinician/BillingAgent opaque), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties & Deterministic Program Clock (append-only WeighIn/Message), 2.5 Hierarchical Consistency/Cascades/Nested Retrieval (13 not-found codes), 2.6 Precision & Rounding, 2.7 OCC on enrollment aggregate (both write endpoints), 2.8 Conserved Quantities, 2.9 Plan Tiers/Risk Bands/Clinical Gating.
- §3. Business Logic (11 subsections): program+catalog, member/coach registration, intake cycle, enrollment activation+first invoice, recurring billing+invoice lifecycle, weigh-ins+dual progress metrics+goals, milestones, coaching assignment+capacity+messaging, eligibility+HSA/FSA, Rx authorization, graduation/withdrawal+settlement cascade.
- §4. Endpoint Definitions — 66 endpoints, 4-column table.
- §5. Error Code Catalogue — 35 errors.

**Hard Contracts:** Contract 1 (field coverage 77/77) PASS; Contract 2 (rule coverage: 2 OCC, all state machines, 11 calculations with constants embedded, 35 error IDs in narrative, sibling-branch symmetry) PASS; Contract 3 (path purity in §3) PASS. §2.2 verified byte-identical to reference template.

## Step 5/6: Unit tests + Implementation (concurrent) — pending

## Step 5: Generate unit tests — 2026-06-07T17:06:00.000Z

Generated complete test infrastructure, translating exclusively from the two design indices.

**Test files: 8** (1 conftest + 7 test modules)
- `test_01_crud_and_access.py` — 9 tests (CRUD, system fields, not-found, required/type validation, RBAC, auth, pagination, append-only immutability)
- `test_02_intake_lifecycle.py` — 6 tests (cyclic revision loop, computed BMI/risk_band, invalid/terminal transitions, precondition enforcement)
- `test_03_enrollment_activation.py` — 9 tests (cross-entity activation/issue gates, intake mismatch, plan retired, Rx required, idempotency, immediate invoice)
- `test_04_progress_and_calculations.py` — 8 tests (scale-vs-lean divergence, eligibility composite, goal progress, lean mass, uncounted exclusion)
- `test_05_billing_and_invoices.py` — 14 tests (round-per-line totals, provisional-vs-prorated, parallel billing dim, period overlap/adjacency, void rules, HSA/FSA, withdraw refund)
- `test_06_cascades_and_coaching.py` — 15 tests (depth-2/3 cascades on graduate & withdraw, graduation boundaries, coach capacity, load conservation, messaging guards)
- `test_07_rx_and_concurrency.py` — 8 tests (Rx BMI boundary, issuance gate ordering, revoke lock, duplicate email, OCC success/stale)

**Total tests: 69.** Queue A (Difficulty §1.8): 36 tests — all 18 difficulty instances × exactly 2 tests each. Queue B (Corner §1.9): 33 tests — all 33 active corner instances ≥1 test each. **0 active instances skipped** (all had verbatim PRD coverage + unique derivability). 6 `excluded_because` stubs correctly NOT translated; all 6 cross-refs resolve to real §1.8 names.

**test_helpers/ files (9):** `__init__.py`, `types.py` (append-only branching for WeighIn/Message), `api_client.py` (66 endpoint methods), `api_errors.py` (35 error IDs + HTTP status map), `assertions.py`, `factories.py` (input-field-only payloads), `constants.py`, `test_users.py` (opaque shared constants + entity-backed `make_coach_headers`/`make_member_headers`), `fixtures.py` (tiered composite setups, OCC-aware weigh-in helpers).

**Verifications:** all modules compile/import; pytest collects 69 with no errors; 69/69 tests carry exactly one verbatim `Design:` tag; 61 docstring citation phrases survive literal grep of PRD.md; no skip/xfail; entity-backed roles use per-instance header builders threaded with real entity ids.

## Step 6: Generate implementation — 2026-06-07T17:06:00.000Z

**Location:** `workspace/implementation/`

**File structure:** `start.sh` (foreground launcher; guarded pip install; exec python3 app.py), `requirements.txt` (flask==3.0.3), `app.py` (Flask entry + blueprint registration + ApiError handler), `db.py` (in-memory Store, 15 dicts keyed by id + new_id()), `errors.py` (full §5 catalogue + ApiError), `response.py` (envelope helpers), `common.py` (common-field init, touch(), validators, pagination), `middleware.py` (X-User-ID/X-User-Role auth + require_roles RBAC), `lookups.py` (type-specific not-found + ISO8601 clock), `calculations.py` (Decimal/ROUND_HALF_UP calcs), `services.py` (cross-entity recompute, auto-achievement, cascade, settlement), `serializers.py` (strip private keys), `routes/` (14 blueprint files).

**Key decisions:** All numeric logic Decimal + ROUND_HALF_UP (BMI, risk band, scale vs lean-adjusted progress, goal progress, eligibility composite, round-per-line invoice totals, chronological proration, HSA/FSA). Deterministic clock reads `program.current_utc` for business timestamps; clock-set rejects backward moves. OCC `expected_enrollment_version` mandatory on weigh-in create + Rx issue, checked after existence before business logic, mismatch→412 ERR_STALE_ENROLLMENT_VERSION. Parallel clinical_status/billing_status evolve independently; cascade order per PRD 3.11. Conserved: coach.active_member_count recomputed from ACTIVE assignments; member.account_balance_cents changes only on proration credit + void reversal. HSA/FSA derived live at invoice read time.

**Storage/reset:** All state in db.py Store (15 dicts). No seeding anywhere — fresh boot = empty collections. start.sh reads $PORT (default 10000), guards pip install, exec python3 app.py binding 0.0.0.0:$PORT foreground threaded. Self-verified via 5 smoke suites (~100 assertions), all passed.

## Step 7: Run tests and iterate — pending

## Step 7: Run tests and iterate — 2026-06-08T01:36:00.000Z

All 8 parallel rounds pass 69/69. The diagnostic loop is complete.

**Iterations run:** 2 (1 diagnosis sweep + 1 verification sweep). Initial baseline was a stable 67/69 across all 8 rounds (2 deterministic failures, no flakiness).

**Tests deleted:** None. Both failures traced to genuine PRD-faithful bugs (one in test_helpers usage, one in implementation), not to PRD-silent or non-derivable assertions.

**Fixes applied to test_suite/ (test setup bug — STEP 2):**
- `test_suite/test_07_rx_and_concurrency.py` :: `test_rx_issue_bmi_gate_fires_when_eligibility_approved` — changed `intake_weight_kg=78` → `86`. The test needs an APPROVED eligibility determination as a precondition (so the referential gate passes and the BMI gate is the one that fires), but a 78 kg / 170 cm member yields BMI 27.0 and composite score 28, below the eligibility-approval threshold of 35 (PRD §3.9), so `create_approved_eligibility` correctly rejected with `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD`. An 86 kg member yields BMI 29.8 (still fails the RX gate: <30.0, no comorbidity → `ERR_BMI_BELOW_RX_THRESHOLD`) while its composite score 39.20 clears the approval threshold, making the precondition reachable. More faithful to PRD, not less.

**Fixes applied to implementation/ (STEP 3):**
- `workspace/implementation/routes/enrollments.py` :: `_issue_recurring_invoice` — derived `period_start_secs` from the program's `current_utc` at operation time (`program_clock_seconds(program)`) instead of `billing_anchor_utc + cycle_index * cycle_length_days`. PRD §2.4 (line 86) is binding: "an invoice's period boundaries [is] read from the owning program's `current_utc` at the moment of the operation." The anchor-offset derivation made `bill-next-cycle` periods always adjacent and never overlapping, so `test_billing_period_half_open_overlap_rejected` wrongly succeeded instead of returning `ERR_BILLING_PERIOD_OVERLAP` (PRD §3.5). Confirmed clean by the 8-round sweep.

**Final result:** 69/69 passing in all 8 concurrent rounds.

**Orchestrator note:** Step 7 subagent's `rm -f results.*.json` at sweep start removed the per-round files on exit; orchestrator independently re-ran the full 8-round parallel sweep to confirm and persist evidence. All 8 rounds 69/69 (results.1.json … results.8.json present). Step 8 NOT skipped (1 implementation/ fix + 1 test_suite/ fix in Step 7).

## Step 8: Finalize PRD — pending

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-07T19:51:09.000Z

All 12 changes are single-line in-paragraph revisions (no new lines, no new sections). The work is complete.

## Summary

Produced `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0242_weight_management_nutrition_program/workspace/PRD_COMPLETED.md` as a minimal in-paragraph patch over `PRD_FINALIZED.md`.

**Counts**
- Source `PRD_FINALIZED.md`: 325 lines, 52,525 chars
- `PRD_COMPLETED.md`: 325 lines (unchanged — all edits in-paragraph), 56,247 chars (+3,722)
- Ambiguity-pins: 8 · Mismatch-revisions: 4 · Total changed lines: 12

**Changes**
- §2.5 (not-found codes) — insert — ambiguity — pinned that an unresolved weigh-in path id returns `ERR_WEIGHIN_NOT_FOUND` and an unresolved message path id returns `ERR_THREAD_NOT_FOUND` (neither is in the catalogue) — `lookups.py:75-76`, `weighins.py:107`
- §3.1 (plan retire) — insert — ambiguity — pinned retire is idempotent/non-state-gated; re-retiring succeeds and bumps `version` — `plans.py:81-87`
- §3.2 (coach update) — revise — mismatch — update is role-only (any `Coach`), no self-ownership check; both fields optional; no-op update leaves `version` unchanged — `coaches.py:74-88`
- §3.4 (invoice lines) — insert — ambiguity — pinned line shape: `line_items` array of `{code, amount_cents}` with codes `RECURRING_FEE`/`ENROLLMENT_FEE`/`PRORATION_CREDIT` — `calculations.py:123-135`
- §3.5 (bill-next-cycle) — insert — ambiguity — pinned no clinical/billing-status precondition; period stamped from `current_utc`, end = start + `cycle_length_days` — `enrollments.py:195-207`, `144-158`
- §3.5 (past-due path) — insert — ambiguity — pinned enrollment state checked first; mark-past-due/pay/void return the target invoice in `data` (not the enrollment) — `invoices.py:67-79`
- §3.6 (goal creation) — revise — mismatch — `progress_pct` is computed at creation from current member state (may be nonzero), and the goal does not auto-achieve at creation — `goals.py:46-48`
- §3.9 (composite score) — insert — ambiguity — pinned that with no `APPROVED` intake, BMI and comorbidity inputs are taken as zero (tier contribution only) — `eligibility.py:39-42`
- §3.9 (hsa_fsa_eligible_cents) — insert — ambiguity — pinned the field is derived live at invoice read time, so approving eligibility retroactively raises it on already-issued invoices — `invoices.py:19-23`
- §3.11 (graduation) — insert — ambiguity — pinned clinical-state checked first; eligibility re-derived (not read from stored flag); settlement invoice `cycle_index` = `cycles_billed` (then incremented), period from `current_utc`, and the zero-credit case (empty `line_items`, `subtotal_cents` 0, `prorated` false, balance unchanged) — `enrollments.py:210-234`, `services.py:202-234`
- §3.11 (proration) — insert — ambiguity — pinned the proration period source is the latest non-`VOID` invoice, and the zero-credit settlement-still-issued behavior — `services.py:185-214`
- §4 (enrollment list row) — revise — ambiguity — pinned the status filter is the `clinical_status` query parameter — `enrollments.py:79,88-89`

**Notes (verified consistent, no change needed):** `created_at`/`updated_at` use wall-clock while business fields read the program clock (matches PRD 2.4); OCC checked before the state gate on Rx issue (matches PRD 2.7 precedence); activate returns 200 (matches §4); non-counted weigh-ins require OCC but don't bump `version` (matches PRD 2.7/3.6).

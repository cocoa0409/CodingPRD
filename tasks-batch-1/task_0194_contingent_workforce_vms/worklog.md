# Worklog — task_0194_contingent_workforce_vms

## Step 1: Create Task Directory — 2026-06-06T00:00:00.000Z

Used pre-allocated directory `tasks/task_0194_contingent_workforce_vms` (no index scan, per orchestration override). Created `workspace/` subdirectory. Confirmed `INSTRUCTION.md` and scaffold-generator skill exist at project root.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-06T00:00:00.000Z

All three files are present, parse cleanly, have correct single top-level keys in the design files, and pass the scaffold lint. The task is complete.

Generated the three required scaffold artifacts for **task_0194_contingent_workforce_vms** at the **Expert** difficulty band. All written to the task dir:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

Generated purely from the scenario + skill spec — no sibling tasks were inspected.

**Profile:** workflow_orchestration + compliance_audit; flat topology; parallel state-machine shape; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. API prefix `/vms` (flat collections so FK reverse-reachability resolves).

**Entities (11):** Program, Supplier, WorkerProfile, Requisition, Distribution, Submittal, Assignment, StatementOfWork, Milestone, Timesheet, Expense. 67 endpoints, 29 error codes, 5 calculations, 17 validations.

**State machines (7):** Requisition (branching + cascade-on-fill), Submittal (cyclic INTERVIEWING⇄RATE_PROPOSED negotiation, capped 5 rounds), Assignment (parallel engagement_status × compliance_status dimensions), StatementOfWork (compound bubble-up to COMPLETED), Milestone / Timesheet / Expense (branching-with-revert rework loops). One OCC concurrency rule: `hire-stale-requisition` on Requisition.version.

**Key calculations:** bill_rate_and_markup (pinned eval order, derived-vs-explicit bill rate, markup ceiling); timesheet_amounts (pinned round-per-component-then-sum with OT multiplier); expense_reimbursement (per-category caps); worker_tenure_rollup (cross-assignment co-employment day conservation, inclusive day counts); distribution_waterfall (cumulative release offsets over distinct supplier tiers).

**Difficulty design (§1.8):** 18 instances — exactly 2 per each of the 9 §0.5 rules.
**Corner design (§1.9):** 36 instances total = 33 active test instances + 3 `excluded_because` stubs (each citing a valid §1.8 instance).

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint` (489 calls scanned, all conform to §1.5; all 16 FKs reverse-reachable).

## Step 3: Copy Shared Files — 2026-06-06T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T00:00:00.000Z

**File written:** `workspace/PRD.md` (308 lines).

**Domain:** Contingent Workforce / Vendor Management System (VMS) — 11 entities, 65 endpoints, 29 error codes, 4 roles, 7 state machines, 5 calculations.

**Major sections produced:**
- **§1 Introduction** — framing the MSP program model, cross-record coupling (tenure rollup, markup, distribution waterfall, hiring race), and the program-scoped logical clock.
- **§2 Global Specifications** (9 subsections) — RBAC with four roles + Supplier entity-backed identity; §2.2 envelope; pagination; common properties + program clock; nested reachability + list filters; monetary precision/round-half-up; OCC on hiring race; hierarchical cascades; eligibility.
- **§3 Business Logic** (11 subsections) — program/supplier/worker setup; requisitions + distribution waterfall; submittals + negotiation loop; bill-rate/markup derivation; hiring + fill cascade; assignment's two parallel dimensions; co-employment tenure rollup + escalation; timesheets; expenses; SOWs + milestones; validation priority order.
- **§4 Endpoint Definitions** — 4-column table, all 65 endpoints under `/vms`.
- **§5 Error Code Catalogue** — 2-column table, all 29 error codes.

**Hard Contracts — all PASS:** Contract 1 (field-name coverage) 52/52 entity props + 40/40 endpoint params; Contract 2 (rule coverage) OCC/validation-priority/cascades/5-calculations all surfaced; Contract 3 (§3 path purity) 459 backtick tokens, 0 path/method leaks.

Withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened.

## Step 5: Generate Unit Tests — 2026-06-06T00:00:00.000Z

Generated complete test infrastructure for **task_0194_contingent_workforce_vms** (Contingent Workforce VMS).

### Files written
- **`test_helpers/`** (9 files): `__init__.py`, `types.py` (12 entity TypedDicts + status/role enums — all entities `common_fields: true` carry `version`/`updated_at`), `api_client.py` (65 endpoint methods), `api_errors.py` (28 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Supplier is the only `entity_backed` role → `make_supplier_headers(id)`; PM/HM/Finance opaque), `fixtures.py` (tiered composite setups).
- **`test_suite/`** (9 files): `conftest.py` + 8 domain-organized `test_*.py` files.

### Test counts
- **70 test functions total**, all collect cleanly + compile.
- **Queue A (Difficulty): 36 tests** — all 18 instances (9 rules × 2) covered, exactly 2 tests each.
- **Queue B (Corner): 34 tests** — all 33 non-stub instances covered (`expense_reimbursement_cap_boundary_meals` got 2; rest 1 each).

### Skipped
- **3 instances skipped**, all `excluded_because` stubs (no `test_recipe`; assertions owned by cited difficulty instances): `error_hire_stale_requisition_version_occ`, `timesheet_pay_vs_bill_dual_variant`, `priority_state_vs_fiscal_conflict`. All 3 stub cross-references resolve to real difficulty instances. **No PRD-first filter skips** were needed — every non-stub instance had verbatim PRD coverage + unique derivability.

### Verification
- Every test docstring ends with exactly one verbatim `Design: Difficulty/…` or `Design: Corner/…` tag.
- Spot-checked ~19 PRD citations via literal grep — all survive verbatim. `pytest --collect-only` reports 70 tests, 0 collection errors.

## Step 6: Generate Implementation — 2026-06-06T00:00:00.000Z

Built a complete Python + Flask REST API in `workspace/implementation/`.

### Files created
- `start.sh` (executable, foreground, reads `$PORT` default 10000, binds `0.0.0.0`, guarded `pip install` + `exec python3 app.py`)
- `requirements.txt` (`flask==3.0.3`)
- `app.py` (entry point, blueprint registration, error handlers, `threaded=True`)
- `db.py` (in-memory dicts, 11 collections, starts empty, no seeding), `errors.py`, `response.py`, `middleware.py`, `validators.py`, `listing.py`, `serializers.py`, `services.py`, `routes/programs.py`, `routes/requisitions.py`, `routes/work.py` (65 endpoints).

### Entities & endpoints
All 11 entities with full CRUD + state-transition actions. Envelope `meta`/`response_type`/`data` + pagination in `meta`; auth via `X-User-ID`/`X-User-Role`; Supplier entity-backed with ownership chains. All 28 error codes + 17-level validation priority order.

### Key calculations (Decimal/ROUND_HALF_UP, verified vs difficulty-design numbers)
- **bill_rate_and_markup**: pinned order; explicit bill verbatim else `rhu(pay×(1+default_markup))`; `effective_markup_pct` exact ratio for inclusive `<=` ceiling (0.60 accept, 0.6001 reject).
- **timesheet_amounts**: round-then-sum per component, OT×1.5 (pay 3127 / bill 4533).
- **expense_reimbursement**: per-category caps, inclusive.
- **worker_tenure_rollup**: inclusive engaged-day count, ON_HOLD accrues, processed start_date→created_at asc (120/90 confirmed).
- **distribution_waterfall**: distinct-tier-index × interval offsets, ties share offset.

### State machines / cascades
Requisition fill cascade (revoke distributions + reject siblings) + `ERR_REQUISITION_HAS_HIRES` guard; Submittal cyclic INTERVIEWING⇄RATE_PROPOSED (5-round cap); Assignment parallel engagement × compliance dimensions, breach forces ON_HOLD, large jumps skip WARNING; SOW bubble-up to COMPLETED on last-milestone invoice; Milestone/Timesheet/Expense reject→rework loops; clock-advance sweeps (release PENDING distributions → auto-approve timesheets → tenure recompute + escalation); `_clock/set` fires no sweeps; OCC `expected_requisition_version` → `ERR_STALE_VERSION` (412).

### Validation
~45 smoke assertions across 5 scripted suites all passed. Clean boot via `bash start.sh` (~0.6s, empty store). `requirements.txt` + `start.sh` written.

## Step 7: Run Tests and Iterate — 2026-06-06T00:00:00.000Z

All 8 parallel rounds pass cleanly (70/70 each). The clean sweep condition is met.

**Iterations run:** 2 (initial sweep surfaced 1 failure; second sweep after the fix was clean).

**Failing test (union across all 8 rounds):** `test_hire_with_correct_version_succeeds_and_bumps_version` — failed deterministically in all 8 rounds of the first sweep with `AssertionError: version 2 -> 4 ... assert 4 == (2 + 1)`.

**Diagnosis (diagnostic protocol):**
- STEP 1a (Coverage): PRD §3.5 states verbatim "The hire then increments the requisition's `filled_count` by one and increments the requisition's `version` by one." Covered.
- STEP 1b (Unique derivability): The outcome is uniquely determined. §3.5 frames the `DISTRIBUTED → FILLED` transition as part of the same hire act, under the single declared "increments the requisition's `version` by one." §2.8's "secondary mutation ... version increments" applies to the *affected records* it enumerates (distributions, sibling submittals) — not to a second self-bump on the requisition. So a single hire that fills a 1-opening requisition must bump the requisition's version by exactly 1. Test kept.
- STEP 2 (Test consistency): The test uses standard fixtures and reads `version` legitimately before/after the hire. Faithful.
- STEP 3 (Implementation fix): The bug was a double `db.touch(req)` on the requisition during a fill — once for the hire's `filled_count` bump, and a second time inside `fill_cascade` which set `status="FILLED"` and touched again. Two version increments instead of one.

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/requisitions.py`, `hire()` — set `req["status"] = "FILLED"` when the seat count is reached *before* the single `db.touch(req)`, so the FILLED transition and the `filled_count` increment share one version bump; `fill_cascade` is then invoked only to propagate to affected records.
- `workspace/implementation/services.py`, `fill_cascade()` — removed the requisition's own `status="FILLED"` assignment and its second `db.touch(requisition)`; the function now only revokes distributions and rejects sibling submittals (each correctly gets its own §2.8 version bump). Net effect: a hire that fills a requisition bumps the requisition's version by exactly 1, matching PRD §3.5.

Final state: all 8 parallel rounds pass 70/70 with zero failures and zero errors.

## Step 8: Finalize PRD — 2026-06-06T00:00:00.000Z

`PRD_FINALIZED.md` was created as a copy of `PRD.md` with **zero edits** — the correct outcome.

**Line counts:** PRD.md = 308; PRD_FINALIZED.md = 308. **Delta: 0 lines (0%).** Files byte-identical.

**Why no edit:** The single `<step_7_diff>` item (the double-version-bump on hire) is a **pure implementation bug**, not a PRD silence or mismatch. PRD §3.5 already determines the behavior verbatim ("The hire then increments the requisition's `filled_count` by one and increments the requisition's `version` by one"), and §2.8 scopes secondary version bumps to *affected records* (distributions, sibling submittals), not a second self-bump on the requisition — so a single fill-hire bumping version by exactly 1 is uniquely derivable. Step 7's fix made code match existing prose; no wording was left open.

**Pre-edit NO-NEW-MISMATCH enumeration (performed even though no edit committed):** subject = requisition `version` increment on hire/fill + FILLED cascade. Enumerated all requisition version-bump paths (distribute, close, cancel-DISTRIBUTED, cancel-DRAFT, hire) + `fill_cascade` + `db.touch`; every path performs exactly one requisition bump per operation, all already stated in PRD prose; no path mis-described. No wording adjustment needed.

## Step 9: Complete PRD — 2026-06-06T00:00:00.000Z

**Files:** Source `PRD_FINALIZED.md` (308 lines, 49,698 chars) → `PRD_COMPLETED.md` (308 lines, 50,562 chars). Char-delta: **+864**. No line-count change (all edits in-paragraph; no new sections).

**Counts:** 4 ambiguity-pins, 2 mismatch-revisions.

**Changes:**
- **§2.4 (Common Resource Properties)** — insert — ambiguity — pinned `version` initial value as **1** — `db.py:45`.
- **§3.2 (Distribution Waterfall)** — insert — ambiguity — pinned that a `distribute` `supplier_id` resolving to no supplier is reported `ERR_SUPPLIER_NOT_ELIGIBLE`, not `ERR_NOT_FOUND` — `routes/requisitions.py:103-105`.
- **§3.5 (Hiring / double-booking)** — insert — ambiguity — pinned that the existing non-`ENDED` assignment's overlap interval runs from its own `start_date` through its `planned_end_date` — `routes/requisitions.py:450-453`.
- **§3.5 (Assignment creation)** — revise — mismatch — replaced "`engaged_days` begins at 0" with the impl reality: `engaged_days` always reflects the live inclusive §3.7 day count (≥1 on hire day when `start_date` ≤ clock, floored at 0 for future starts); also pinned compliance seed name-mapping `CLEAR→CLEAR`, `WARNING→TENURE_WARNING`, `BREACH→TENURE_BREACH` — `routes/requisitions.py:470-474, 496-501`; `services.py:76-84`.
- **§3.7 (Tenure rollup)** — insert — ambiguity — noted inclusive ACTIVE/ON_HOLD day count floored at 0 when clock precedes `start_date` — `services.py:84`.
- **§3.8 (Timesheets)** — insert — ambiguity — pinned that a created `DRAFT` timesheet carries `submitted_at` null and `pay_amount_cents`/`bill_amount_cents` at 0 until approval — `routes/work.py:60-71`.
- **§3.9 (Expenses)** — insert — ambiguity — pinned that a created `DRAFT` expense carries `reimbursable_amount_cents` at 0 until approval — `routes/work.py:203-212`.

**Key findings:** Impl already pins most PRD behaviors uniquely (rounding, waterfall offsets, negotiation cap, fill cascade, SOW not-to-exceed, RBAC, error catalogue, priority ordering). The only genuine mismatch was the assignment `engaged_days` "begins at 0" prose, contradicted by live-on-read computation. Tests used only as cross-reference.

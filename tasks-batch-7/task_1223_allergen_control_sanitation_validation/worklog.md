# Worklog — task_1223_allergen_control_sanitation_validation

## Step 1: Create Task Directory — 2026-08-12T01:05:00.000Z

Task directory pre-assigned as `tasks/task_1223_allergen_control_sanitation_validation` with `workspace/` subdirectory already created. Step 1 treated as done per pipeline input instructions.

## Step 2: Generate Scaffold — 2026-08-12T01:24:00.000Z

All three artifacts generated and lint-clean. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts

- **13 entities**: Allergen, ProductionLine, Product, LineAllergenMatrixEntry, ProductionRun, Changeover, ChangeoverProcedure, SwabResult, QaTechnician, LabelReconciliation, ReworkBatch, Incident, AuditFinding
- **67 endpoints** (incl. `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-05-01T00:00:00Z` default, and a business endpoint for supplier allergen change)
- **9 state machines**, several non-linear: Changeover has a SWAB_PENDING↔REWORK_REQUIRED cycle; ProductionRun has DRAFT↔SCHEDULED cycle; ProductionLine is a compound posture-driven machine (OPEN/RESTRICTED/HOLD derived from Incident + Changeover state); QaTechnician has threshold auto-transition
- **9 calculations** covering dual-variant (`introduced_allergens` optimistic_preview vs strict_actual; `training_score` computed vs reinstate-floor), combinatorial mode (a) (`changeover_validation_score`, multi-input with floor/cap/clamp), combinatorial mode (c) (`line_posture`, pinned HOLD>RESTRICTED>OPEN evaluation order), set-difference, threshold with strict-`<` boundary, half-open interval overlap
- **20 ordered validations** (auth → existence → OCC → state → safety → constraint → temporal → referential → fiscal), **47 error codes**, **5 roles** (segregation-of-duties role model; QaTechnician/Auditor are entity-backed)
- **2 OCC concurrency rules** (`run-schedule-stale-line`, `procedure-approve-stale-family`), each wired to `expected_*_version` + 412

## Difficulty design (§1.8)

**18 instances, 2 per rule**, each with structured `setup_api_calls` / `trigger` / literal-computed asserts (e.g., validation_score pinned to 94; training-score 100→98→100 waive-refund invariant; 8×MAJOR = 60 stays ACTIVE, +MINOR = 58 suspends). Rule differentiation honored: dual-variant instances span different entity domains (run allergens vs technician score); combinatorial instances hit modes (a) and (c); cascades use different triggers (swab-fail vs run-cancel); priority conflicts use different error-category pairs (state-vs-safety, safety-vs-fiscal); boundaries use different metrics/endpoints (ppm equality vs half-open interval); temporal-overlap rules use different interval semantics (half-open vs aggregate budget).

## Corner design (§1.9)

**39 instances across 9 sections** (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model), including 1 `excluded_because` stub pointing at the §1.8 swab-boundary instance.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(67 endpoints, 13 entities, 18 §1.8 + 38 active §1.9 instances, 442 calls scanned.) Initial run reported 12 FK_REVERSE_UNREACHABLE violations, fixed by adding filter params (`from_run_id?`, `procedure_id?`, `target_allergen_id?`, `recorded_by_id?`, `source_product_id?`, `product_id?`, `allergen_id?`, `source_label_reconciliation_id?`, `source_changeover_id?`, `auditor_id?`) to existing list endpoints plus a single-GET for LineAllergenMatrixEntry.

Note: the task directory already contained a `worklog.md` and `workspace/` before I started; I did not touch them.

## Step 3: Copy Shared Files — 2026-08-12T01:25:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1223_allergen_control_sanitation_validation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T01:37:00.000Z

The PRD is generated and fully verified. `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/PRD.md` exists (362 lines, ~7,100 words).

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/PRD.md`

**Section list:**
- §1. Introduction (3 paragraphs: business context → system scope → role/posture overview)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (5 roles, identity prose for entity-backed `QaTechnician`/`Auditor` vs opaque `QaManager`/`QaSupervisor`/`LineOperator`)
  - 2.2 API Response Structure (emitted byte-for-byte verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (`limit` default 10/min 1/max 100, `offset` default 0, `created_at` ascending, meta fields)
  - 2.4 The Logical Clock (startup default 2026-05-01T00:00:00Z, overdue sweep, non-retroactive certification expiry)
  - 2.5 Line Posture: The Derived Safety Gate (pinned HOLD→RESTRICTED→OPEN evaluation order, posture gates)
  - 2.6 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`; derived-field recomputes mutate; line-version bumps on schedule/begin)
  - 2.7 Optimistic Concurrency Control (both OCC rules with `expected_line_version`/`expected_procedure_version`, 412s)
  - 2.8 Validation Cascade and Nested Resource Resolution (12-step ordered cascade mirroring the 20 validation priorities, left-to-right 404s)
  - 2.9 Numbers, Thresholds, and Rounding (integer minutes/scores, clamp 0–100, strict-inequality swab comparison)
- §3. Business Logic & Workflows (9 subsections: 3.1 Allergen master data & matrix · 3.2 Products, rework classes & label revisions · 3.3 Procedure versioning · 3.4 Run scheduling & changeover gate · 3.5 Changeover execution & swab verification · 3.6 Label reconciliation · 3.7 Rework containment · 3.8 Incident escalation · 3.9 Technician certification, training & audit)
- §4. Endpoint Definitions (status-code paragraph + 67-row, 4-column table — method/path set verified identical to scaffold)
- §5. Error Code Catalogue (47-row, 2-column table — all IDs and HTTP statuses verified identical to scaffold)

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + common fields: 89 required, 89 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 20 checked, expressed as the 12-step §2.8 cascade plus pinned orderings in §3.3 (approve), §3.4 (schedule: OCC before state), §3.7 (class gate precedes allergen breach), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_*_version + exact error_id + HTTP 412), 0 missing
- state_machines[].transitions: 9 machines (incl. derived ProductionLine posture), all from/to pairs, preconditions with error IDs, and side effects expressed, 0 missing
- calculations[]: 9 checked (introduced_allergens with both optimistic/strict variants, changeover_required, scheduled_changeover_minutes, changeover_validation_score with all 7 constants, swab_outcome strict inequality, training_score with 60-suspend/75-reinstate, label verdict precedence, rework two-rule order, line posture), all in precise prose, 0 missing
- validations[] conditions: 47 error IDs all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: expressed (cancel cascades, FAIL-cluster incident+HOLD, escalate force-pause, supplier-change stale-pin, multi-endpoint applies_to scopes), 0 missing
- entities[].fields[] structured content: defaults, nullables, computed sources reconstructible from prose
- sibling-branch symmetry: parallel branches (cancel from DRAFT vs SCHEDULED, four rework classes, three swab-failure verdicts, four label verdicts) rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 529
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: §2.2 verbatim block byte-identical; all 72 enum/state values present in backticks; all 5 role names exact. The two withheld difficulty/corner design files were not opened.

## Step 5: Generate Unit Tests — 2026-08-12T02:05:00.000Z

All checks pass. Final summary:

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/test_helpers/`** (9 files)
- `types.py` — 12 entity TypedDicts + status/enum classes + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (60+ methods), `api_client` singleton
- `api_errors.py` — `ApiErrorId` (48 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (common fields + enum domains) and a rework mass-conservation invariant
- `factories.py` — payload factories, input fields only
- `constants.py` — thresholds (suspension 60, reinstate 75, deductions 2/5/15, overdue 3, score clamps, pagination)
- `test_users.py` — opaque role constants + mandatory `make_qa_technician_headers` / `make_auditor_headers` builders for the two entity-backed roles
- `fixtures.py` — composite helpers: `setup_changeover_scenario` (allergen→line→matrix→product→approved procedure→certified tech→run→changeover→schedule), `setup_swab_pending_changeover`, `drive_changeover_to_swab_pending`, `record_swab`, `schedule_run` (fresh OCC token), technician-pair/finding/incident drivers
- `__init__.py` — barrel export

**`/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/test_suite/`** (7 files, **70 tests**)
- `conftest.py`, `test_01_master_data_and_rbac.py`, `test_02_run_scheduling_gates.py`, `test_03_overlap_occ_and_listing.py`, `test_04_changeover_swab_validation.py`, `test_05_label_reconciliation_and_incidents.py`, `test_06_rework_containment.py`, `test_07_technician_training_and_procedures.py`

## Per-queue coverage

**Queue A (Difficulty): 15 of 18 instances translated, 2 tests each (30 tests). 3 skipped** under the PRD-first two-condition filter:
1. `transitive_cascade/swab_fail_cluster_cascade_changeover_incident_line_hold_depth3` — the recipe's path (FAIL → reswab → FAIL) cannot reach `FAILED`: PRD §3.5 states reswab marks prior FAILs INVALIDATED "clearing them from the failure count", so the second FAIL leaves count=1 → `REWORK_REQUIRED`. A single FAIL also immediately ejects the changeover from `SWAB_PENDING` (`ERR_SWAB_NOT_PENDING` on any other state), so count=2 is unreachable via public endpoints. PRD affirmatively derives a different outcome than the instance asserts.
2. `transitive_cascade/run_cancel_cascade_changeover_swab_invalidate_depth2` — PRD §3.4's run-cancel cascade reaches only changeovers in `PLANNED`/`IN_EXECUTION`; at the recipe's trigger point the changeover is `SWAB_PENDING`/`VALIDATED`, so PRD derives *no* cascade. (Additionally, swabs cannot exist on an `IN_EXECUTION` changeover, making the mid-flight invalidation branch unobservable.)
3. `priority_pair_validation_conflict/business_safety_vs_business_fiscal_rework_commit` — PRD §3.7 pins class-gate-first: "a commit that violates both surfaces `ERR_REWORK_CLASS_VIOLATION`, never the allergen breach", directly contradicting the asserted `ERR_REWORK_ALLERGEN_BREACH` (§2.8's cascade order conflicts with §3.7; not uniquely derivable).

**Queue B (Corner): all 38 non-stub instances translated (39 tests; two instances got a second angle — prohibited-at-creation, procedure-approve supersession).** The one stub (`excluded_stub_swab_boundary`) was not translated; its cross-reference `boundary_precision_check / swab_action_level_exact_equality_is_fail` resolves.

Notable recipe repairs made to stay PRD-legal while preserving each instance's claim: swab ordering adjusted so `INVALIDATED`/extra swabs land before validation completes; score-margin clamp test uses `min_swab_zones=3`; overlap rejections exercised at both creation and schedule; procedure-OCC stale token via genuine version mismatch (PRD §2.7 checks the procedure's own version, not family state); supplier-change test uses a genuinely changed allergen set (`[MILK]`→`[SOY]`) so the auto-incident is unambiguous.

## Stage 2 lint/audit outcome
- `py_compile`: all 16 files pass; `pytest --collect-only`: **70 tests collected**, zero import errors
- Design-tag audit: every test has exactly one final-line `Design:` tag; all 70 tags resolve to real instances; coverage thresholds met (≥2 per translated difficulty instance, ≥1 per non-stub corner instance, 0 on the stub)
- Verbatim pass: every ≥6-word quoted citation survives a whitespace-normalized literal grep of `PRD.md` (initial run caught 10 elided quotes; all rewritten to full verbatim sentences and re-verified)
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; entity-backed roles use per-instance header builders wherever identity is checked (swab recording, audit creation)

## Step 6: Generate Implementation — 2026-08-12T02:05:00.000Z

Done. The implementation is complete and boot-verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/implementation/`):

- `start.sh` — foreground launcher: guards the pip install (`import flask` check), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — Flask
- `app.py` — app factory, envelope-shaped error handlers (ApiError, 400/404/405, generic)
- `db.py` — in-memory stores (12 entity dicts), logical clock starting exactly at `2026-05-01T00:00:00Z`, UUID ids, `created_at`/`updated_at` (ISO 8601, 3 fractional digits), `version` counter, `_seq` for stable sort tiebreaks
- `errors.py`, `response.py`, `util.py`, `middleware.py` — error catalog carrier, exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp` + pagination fields, `response_type`, `data`; errors as `data.error_id`/`message`), body/field/datetime/pagination validators, `X-User-ID`/`X-User-Role` auth with the five roles
- `logic.py` — line-posture recompute (pinned HOLD→RESTRICTED→OPEN order), training-score recompute (un-refunded overdue penalty tracked per finding), introduced-allergen diff (optimistic vs strict variants), changeover gating/budgets, swab convergence (1 FAIL → REWORK_REQUIRED, ≥2 FAIL → FAILED + auto SWAB_FAILURE_CLUSTER incident + HOLD, zones-met → VALIDATED), validation score (base 100, +5 on-time, tardy −1/5min cap 20, margin bonus cap 10, −2 per invalidated, clamped 0–100), auto-incident helper
- `routes/` — 14 blueprints: clock, allergens, lines, matrix, products (+PATCH, +supplier-allergen-change), runs (7 transitions incl. OCC `expected_line_version`), procedures (approve/retire with `expected_procedure_version` OCC + family supersede), changeovers, swabs (cert/expiry personnel gates), technicians, findings, recons, reworks, incidents (segregation-of-duties on close)

**Endpoint count:** 67 routes registered — matches the scaffold/PRD endpoint table exactly.

**Verification results:**
- `py_compile` clean on all modules
- Booted via `cd implementation && PORT=18123 bash start.sh`; ready within ~1s
- 63-check end-to-end smoke test passed (0 failures), covering: auth header/role errors, clock set, CRUD + uniqueness + code-format validation, OCC 412s, run lifecycle with overlap/changeover gates, exact-action-level FAIL semantics, reswab invalidation, validation score, posture transitions (RESTRICTED/HOLD/OPEN), label recon verdicts/escalation with CRITICAL incident + segregation-of-duties close, training-score auto-suspend at <60, reinstate to 75, overdue sweep with non-refunded penalty, rework class-gate ordering, pagination meta, and 404 envelope
- Kill + fresh relaunch on a new port returns `total_count: 0` — in-memory store resets cleanly per boot, satisfying `per-test-server` isolation. No seeding anywhere at startup.

Orchestrator route-parity check (pre-Step-7): 67 (method, path) pairs declared in SCAFFOLD.yaml, 67 registered in the Flask app — MISSING: none, EXTRA: none.

## Step 7: Run Tests and Iterate — 2026-08-12T02:20:30.000Z

All 8 rounds pass 70/70 with zero errors. The fix is verified stable under the parallel sweep.

## Summary

**Iterations run:** 3 sweeps total. Sweep 1 (baseline): 68/70 in all 8 rounds — 2 deterministic failures. Sweep 2: invalidated by an external SIGKILL (all 8 pytest processes killed simultaneously at ~104s by another pipeline on this shared 8-core host; not a test or implementation signal). Sweep 3 (post-fix): 70/70 in all 8 rounds, 0 errors — clean exit condition met.

**Failing tests (union, deterministic across all rounds):**
- `test_02_run_scheduling_gates.py::TestIntroducedAllergensDualBaseline::test_optimistic_preview_empty_then_strict_introduces_peanut`
- `test_02_run_scheduling_gates.py::TestIntroducedAllergensDualBaseline::test_strict_recompute_sets_changeover_required_and_minutes`

Both failed with 409 `ERR_CHANGEOVER_MISSING` when scheduling a second run whose still-SCHEDULED same-product predecessor was counted in the optimistic creation preview (`changeover_required=false`) but excluded by the strict schedule-time baseline (`changeover_required=true`).

**Diagnostic outcome:**
- STEP 1a/1b: PRD §3.4 verbatim covers the rule and pins the sequence — gates listed first ("the OCC check fires first... The remaining gates follow: ... if `changeover_required` is true, a covering changeover targeting this run must already exist..."), with the strict recompute explicitly an "On success" effect. Every gate reads current stored state, and `changeover_required` is a stored attribute pinned at creation. Unique derivability holds; no test tension (the only other `ERR_CHANGEOVER_MISSING` test uses a first-run-on-line scenario where stored == strict == true).
- STEP 2: Tests were faithful (setup, QaSupervisor role, fresh OCC token, assertions all match PRD).
- STEP 3: Implementation bug.

**Tests deleted:** none.

**test_helpers/ fixes:** none.

**implementation/ fixes:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/implementation/routes/runs.py` — `schedule_run()`: the `ERR_CHANGEOVER_MISSING` covering-changeover gate now evaluates the run's stored (optimistic) `changeover_required` instead of the strict-recomputed value, and the gate was moved ahead of the strict recompute to match PRD §3.4's pinned ordering (gates on stored state first; "On success" strict recompute of `introduced_allergens`/`changeover_required`/`scheduled_changeover_minutes` after). The prohibited-allergen re-check at scheduling remains in force via the recompute path.

Orchestrator verification: all 8 results files exist on disk; each reports passed=70, total=70, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-12T02:25:00.000Z

PRD_FINALIZED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/PRD_FINALIZED.md`. It differs from PRD.md by exactly one in-place paragraph revision.

**Line counts / delta:** PRD.md = 362 lines, PRD_FINALIZED.md = 362 lines, 0% delta (one line revised in place).

**Change log (one edit):**
- §3.4 (Production Run Scheduling and the Changeover Gate) — revise — the `ERR_CHANGEOVER_MISSING` covering-changeover gate is now pinned to read the run's *stored* `changeover_required` (the optimistic value pinned at creation, cleared by unscheduling) with no strict recomputation ahead of the gate; the strict recomputation of `introduced_allergens`, `changeover_required`, and `scheduled_changeover_minutes` is pinned as an on-success effect after all gates pass, with the stored-back result and the note that this recompute is what re-enforces the prohibited-allergen rule at scheduling — `implementation/routes/runs.py:105-117` (gate at 107, strict recompute at 111-112, write-back at 115-117), helpers `implementation/logic.py:63-98`.

**Per-edit pre-edit search log:**
- (a) Subject: which `changeover_required` value the scheduling-time covering-changeover gate consults (stored optimistic vs. strict-recomputed), and the ordering/persistence of the strict recompute of the three derived run fields.
- (b) Impl paths enumerated and read: `implementation/routes/runs.py` in full — `create_run` (lines 45-46, 57-58: optimistic compute and storage at creation), `schedule_run` (lines 105-117: stored-value gate, strict recompute, write-back of all three fields, line version bump), `unschedule_run` (lines 131-133: clears all three fields to `[]`/`False`/`0`), `start_run` (lines 148-152: reads stored `changeover_required` for the `ERR_CHANGEOVER_NOT_VALIDATED` gate); `implementation/logic.py` in full — `compute_introduced` (63-76: optimistic adds `SCHEDULED` to baseline statuses), `compute_changeover_needs` (79-98: raises `ERR_ALLERGEN_PROHIBITED_ON_LINE`, computes required/minutes), `covering_changeover` (101-107); `implementation/routes/changeovers.py:25-27` (budget gate reads the to-run's stored `scheduled_changeover_minutes`). Grep confirmed no other readers/writers of `changeover_required`, `scheduled_changeover_minutes`, or the two error sites.
- (c) Wording adjustments made for cross-path consistency: (1) described the gate value as "the value currently stored on the run (pinned optimistically at creation; cleared by unscheduling)" rather than just "the optimistic value pinned at creation," because `unschedule_run` overwrites the stored value with `False` — naming only the creation value would have mis-described the unschedule→reschedule path; (2) included `scheduled_changeover_minutes` in the on-success recompute/write-back list, matching `runs.py:117`, which matters downstream because changeover planning's budget gate (`changeovers.py:25`) reads that stored field; (3) kept the recompute as an "only on success" effect rather than pinning an execution interleaving with the overlap check, since the observable error precedence (prohibited-allergen 422 before overlap 409) is already pinned by the §2.8 cascade ordering (business-safety step 7 before business-constraints step 8), matching `runs.py:111-113`.

No other edits were made — the step_7_diff contained exactly one implementation fix, no test/test_helper changes, and no deletions.

## Step 9: Complete PRD — 2026-08-12T02:40:00.000Z

The patch is complete and verified. Final report:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1223_allergen_control_sanitation_validation/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, edited in place; no new sections added, all changes are inline inserts/revisions).

**Size delta:** 362 lines / 52,481 chars → 366 lines / 56,631 chars (**+4 lines, +4,150 chars**), across 40 diff blocks.

**Counts:** 23 ambiguity-pins, 10 mismatch-revisions (33 change units total).

### Changes

- §2.1 — insert — ambiguity — unrecognized role string counts as malformed header (400, not 403); `X-User-ID` must be non-empty — `middleware.py:16`
- §2.2 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` 404 in standard envelope — `app.py:23-29`
- §2.3 — insert — ambiguity — equal `created_at` ties ordered by server creation sequence — `response.py:30`
- §2.4 — insert — ambiguity — clock settable to any instant (forward or backward); sweep only moves `OPEN`→`OVERDUE`, never reverses — `clock.py:17-23`
- §2.5 — revise — mismatch — posture-recompute trigger list extended with reswab (`REWORK_REQUIRED`→`SWAB_PENDING`) — `changeovers.py:109-111`
- §2.6 — insert — ambiguity — `version` starts at 1 at creation — `db.py:37`
- §2.8 item 5 — insert — ambiguity — product-activity gate (`ERR_PRODUCT_INACTIVE` 422) placed at source-state step, before posture gates — `runs.py:100-104`
- §2.8 — insert — ambiguity — endpoint-specific gate orders pinned in §3 (§3.4, §3.7) govern over the generic step numbering — `runs.py:107-114`, `reworks.py:62-91`
- §3.1 — insert — ambiguity — duplicate allergen `code` → `ERR_INVALID_REQUEST` 400 — `allergens.py:25-26`
- §3.1 — insert — ambiguity — duplicate `line_code` → `ERR_INVALID_REQUEST` 400 — `lines.py:20-22`
- §3.1 — insert — ambiguity — `changeover_minutes` is a non-negative integer; duplicate `(line_id, allergen_id)` rows permitted and all consulted — `matrix.py:22`, `logic.py:84-90`
- §3.2 — insert — ambiguity — duplicate `sku` → 400; `label_revision` integer ≥ 1; patch counts as mutation even if value unchanged; `allergen_set` compared as a set (reorder = no incident); patch/supplier-change do not re-validate against active allergens — `products.py:32-36,73-107`
- §3.4 — insert — ambiguity — `introduced_allergens` listed in ascending code order — `logic.py:76`
- §3.4 — insert — ambiguity — covering-changeover gate enumerated exactly (`PLANNED`/`IN_EXECUTION`/`SWAB_PENDING`/`REWORK_REQUIRED`/`VALIDATED`; `CANCELLED`/`FAILED` do not cover) — `runs.py:13-14,107`
- §3.4 — revise — mismatch — scheduling gate order: strict recomputation (which re-enforces the prohibited-allergen rule) runs **before** the overlap re-run, not after — `runs.py:110-114`
- §3.4 — insert — ambiguity — unschedule also resets `scheduled_changeover_minutes` to 0 — `runs.py:131-133`
- §3.4 — insert — ambiguity — run-cancel cascade invalidates only swabs not already `INVALIDATED` — `runs.py:209-214`
- §3.4 — insert — ambiguity — start consumes the most recently created `VALIDATED` covering changeover; the changeover itself is unmodified — `logic.py:101-107`, `runs.py:147-161`
- §3.4 — revise — mismatch — completion gate: an `OPEN` reconciliation with verdict `MATCH` does **not** block; the block is "neither `MATCH`-verdicted nor `RESOLVED`" (PRD had said any `OPEN` recon blocks) — `runs.py:170-175`
- §3.5 — insert — ambiguity — changeover planning applies no posture, to-run-state, or procedure-state gate; only the budget rule — `changeovers.py:15-39`
- §3.5 — revise — mismatch — validation requires **two** conditions (distinct `PASS` zones ≥ `min_swab_zones`, and no `FAIL`); the PRD's third condition (required ELISA swab with `PASS`) is not implemented — `logic.py:182-190`
- §3.5 — revise — mismatch — reswab invalidates **every** `FAIL` swab on the changeover (not zone-scoped) and recomputes posture — `changeovers.py:102-111`
- §3.6 — insert — ambiguity — escalation accepts any `OPEN` reconciliation, including a `MATCH` one — `recons.py:87-95`
- §3.6 — revise — mismatch — replaced "IN_PROGRESS run force-paused until incident reaches `CONTAINED`" with the actual mechanism: the escalated (terminal, non-`MATCH`) reconciliation permanently fails the §3.4 completion gate — `recons.py:92-108`, `runs.py:170-175`
- §3.7 — insert — ambiguity — `quantity_kg` must be > 0 at creation and at commit (`ERR_INVALID_REQUEST` 400) — `reworks.py:20-22,59-61`
- §3.8 — insert — ambiguity — segregation trigger-user provenance: FAIL-swab recorders for swab clusters, reconciliation creator for label escalations, none for manual incidents (check can never fire) — `logic.py:163-172`, `recons.py:104`, `incidents.py:54,116`
- §3.8 — revise — mismatch — posture recomputed unconditionally on close and on void (PRD conditioned it on "last CRITICAL" / "any HOLD it had caused") — `incidents.py:120-123,133-135`
- §3.9 — insert — ambiguity — duplicate `tech_code` → 400; each `certified_allergen_ids` entry must resolve to an existing allergen (`ERR_NOT_FOUND`) — `technicians.py:20-26`
- §3.9 — revise — mismatch — overdue penalty applies to findings standing at `OVERDUE` **or `RESOLVED`** once incurred (PRD said only `OVERDUE`), never refunded — `logic.py:53-55`
- §3.9 — insert — ambiguity — manual suspend requires `ACTIVE`: `SEPARATED` → `ERR_TECH_TERMINAL` 409, other non-`ACTIVE` → `ERR_TECH_NOT_ACTIVE` 403 — `technicians.py:58-63`
- §3.9 — revise — mismatch — reinstatement resets `training_score` to exactly 75 (PRD said "a floor of 75") — `technicians.py:77`
- §4 table (13 rows) — insert — ambiguity — named exact-match filter query params for every list endpoint — `routes/*.py` list handlers
- §4 table — revise — mismatch — escalate row description "non-MATCH reconciliation" → "OPEN reconciliation" — `recons.py:87-90`

# Worklog — task_0379_translation_localization_services

## Step 1: Create Task Directory — 2026-06-16T00:00:00.000Z

Created `tasks/task_0379_translation_localization_services/` and `workspace/` subdirectory using the pre-assigned index (no scan/auto-increment). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-16T00:00:00.000Z

All three required files written and validated at task dir: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

**Complexity profile:** pricing_engine + workflow_orchestration; flat topology; cyclic state-machine shape; segregation_of_duties role model; immediate consistency.

**Scaffold metrics (Expert band):**
- **Entities:** 10 — Client, Linguist, RateCard, Project, ProjectJob, Assignment, QAReport, Invoice, PayoutLedgerEntry (append-only event log), DeliveryCertificate
- **State machines:** 4 (Project, ProjectJob, Assignment, Invoice) — ProjectJob carries the cyclic IN_QA↔REVISION revision loop; Invoice has branch-with-revert (ISSUED→VOIDED reverts Project)
- **Calculations:** 4 — quote_estimate (forward-looking), final_invoice (chronological dual-variant), linguist_payout (provisional/final variants), qa_score (weighted MQM-style)
- **Validations:** 12 (priority-ordered, 8 categories)
- **Endpoints:** 39 (incl. 14 FK reverse-reachability GETs and OCC-guarded writes)
- **Errors:** 19 — all triggered by a design instance
- **Roles:** 5 — ProjectManager, AccountsReceivable (opaque); Client, Translator, Reviewer (entity_backed)
- **Concurrency rules:** 2 OCC (assignment-create on ProjectJob.version; invoice-issue on Project.version)

**Design instances:**
- **§1.8:** 18 instances (9 difficulty rules × 2)
- **§1.9:** 43 instances (36 active recipes + 7 `excluded_because` stubs) across all 9 claim-extraction sections

`scaffold_lint.py` returns VERDICT: clean lint (574 calls checked; all 14 FKs reverse-reachable). Rule 8 fix: Linguist per-day aggregate-capacity (ERR_THROUGHPUT_EXCEEDED) vs ProjectJob half-open per-job window collision (ERR_WINDOW_OVERLAP).

## Step 3: Copy Shared Files — 2026-06-16T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-16T00:00:00.000Z

**Output:** `workspace/PRD.md` — 264 lines, 5 top-level sections, 23 subsections.

Coverage confirmed (all scaffold artifacts in prose):
- Entities 10/10 (RateCard & PayoutLedgerEntry flagged common_fields:false)
- State machines 4/4 (Project 7, ProjectJob 7 incl. cyclic REVISION↔IN_QA, Assignment 7, Invoice 4 incl. INVOICED→DELIVERED void-revert)
- Calculations 4/4 (quote_estimate, final_invoice, linguist_payout dual-variant, qa_score) — constants embedded, per-band-then-sum rounding, round-half-up pinned
- Validations 12/12 priority-ordered in §2.6
- Concurrency rules 2/2 OCC (ERR_STALE_VERSION/412)
- Endpoints 39/39, Errors 19/19, Roles 5/5

Hard contracts all PASS: field coverage (67/67), rule coverage, path-purity (0 path tokens in §3). Withheld difficulty/corner design files not opened.

## Step 5: Generate Unit Tests — 2026-06-16T19:09:29.000Z

Complete. The full test infrastructure and suite have been generated and verified.

Generated complete test infrastructure for the Translation & Localization Services PRD benchmark task (task_0379), translating exclusively from the two design indices.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — entity TypedDicts with correct `common_fields` branching (RateCard and PayoutLedgerEntry carry only `id`+`created_at`, no `version`/`updated_at`), status/role enums
- `api_client.py` — 45 endpoint methods (one per PRD endpoint row)
- `api_errors.py` — all 19 error IDs + HTTP status map registered with the framework
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with mandatory per-instance builders for the three entity-backed roles), `fixtures.py` (5-tier composite chains: foundations → in-progress → in-QA → QA-passed → delivered → issued-invoice), and the barrel `__init__.py`

**Stage 2 — `test_suite/` (conftest + 8 domain-grouped files, 72 tests):**

Coverage audit (all green):
- **18/18 difficulty instances** each have ≥2 Design-tagged tests (36 difficulty-tagged tests total)
- **36/36 non-stub corner instances** each have ≥1 Design-tagged test
- **7/7 excluded stubs** correctly skipped (none tagged); all their `difficulty_instance` cross-references resolve to real difficulty names
- Every test has exactly one `Design:` tag; 72 tests / 72 tags

Verification performed:
- All 72 tests collect under pytest with no import/syntax errors
- All 101 PRD citation chunks survive verbatim grep of PRD.md (ellipsis-spliced fragments checked per-side)
- No `skip`/`skipif`/`xfail`; no scaffold-language leakage in generated code
- No calls to non-existent ApiClient methods or test_helpers names
- **Every literal expected value independently recomputed from PRD formulas and confirmed**: provisional payout 15975, final payout 17719 (96.2 bonus), quote 39613, final invoice 44313 (2 rev rounds), single-pass 42063, volume boundary 71250/74985, notarized 84750, per-band-rounding 12036, and all QA scores (88.5/99.6/90.0/89.6/0.0/96.2)

No instances were skipped under the PRD-first filter — every reviewed instance had verbatim, uniquely-derivable PRD coverage.

## Step 6: Generate Implementation — 2026-06-16T19:09:29.000Z

I generated a complete Python + Flask implementation for the Translation & Localization Services API at `workspace/implementation/`.

### Structure
- `start.sh` — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), binds `0.0.0.0:$PORT` (default 10000), uses `exec`.
- `app.py` — entry point, blueprint registration, error handlers (maps `ApiError` to the scaffold's exact error envelope; 404/405/400/unexpected fallbacks).
- `db.py` — in-memory store (starts empty every boot, no seeding), UUID + timestamp + version helpers.
- `response.py` — exact envelope (`meta`/`response_type`/`data`, `req_` IDs, ISO-8601 UTC with 3 fractional digits, pagination fields in `meta`).
- `errors.py`, `middleware.py`, `serializers.py` — error catalog, `X-User-ID`/`X-User-Role` auth + RBAC, per-entity output shaping.
- `services/calc.py` — the four calculations using `Decimal`/`ROUND_HALF_UP` with pinned per-band-then-sum rounding.
- `services/{helpers,lookups,workflow}.py` — pagination, ledger reconciliation, existence lookups, cascade-cancel + bubble-up propagation.
- `routes/*.py` — all 39 endpoints across clients, linguists, rate-cards, projects, jobs, assignments, qa-reports, invoices.

### Validated behaviors (end-to-end smoke tests)
- Full lifecycle: client → rate-card → linguists → project → jobs → quote → approve → assign → accept → submit → QA → deliver → certificate → invoice → issue → pay/void.
- **Calculations match exact expected cents**: quote estimate (subtotal 215000, EXPRESS rush → 287500), final invoice with volume/rush/revision surcharge/cert composition, linguist payout (provisional 129000 → final 135450 with +5% QA bonus), QA score rounding (84.985 → 85.0, negative floored to 0.0), revision surcharge (2 rounds − 1 free = 1600 cents).
- **State machines + propagation**: job PENDING→TRANSLATING→IN_QA→REVISION↔IN_QA→QA_PASSED→DELIVERED; project auto-advance to IN_PRODUCTION/DELIVERED/INVOICED; void compensation reverts project INVOICED→DELIVERED and AR balance.
- **Ledger consistency**: COMMIT/REVERSAL/FINAL_ADJUST entries keep `committed_payout_cents` and `ar_balance_cents` reconciled.
- **Validation precedence (PRD §2.6)**: header → role → existence → body → state → business rules, verified (e.g., missing-header beats 404, wrong-role beats 404, missing-resource beats body validation).
- **Edge rules**: OCC stale version (412), segregation violation, half-open window overlap (touching endpoints allowed, interior rejected), throughput cap per shared UTC day, qualification, suspended client blocking, empty analysis, no jobs, pagination clamping (limit 0→1, 500→100).

### Key design notes
- Certificate numbers are re-derived on each mint by sorting the project's certificates by job `created_at` ASC (handles out-of-order delivery), assigned as integers.
- Fresh boot is fast (~500ms; pip skipped when flask present) and the store is empty, satisfying `--isolation per-test-server`.

All structural names (headers `X-User-ID`/`X-User-Role`, envelope `meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more`, OCC fields `expected_job_version`/`expected_project_version`, all error IDs) were read directly from the PRD/scaffold, not assumed.

## Step 7: Run Tests and Iterate — 2026-06-16T20:02:57.000Z

All clean. Final summary below.

---

## Summary

**Iterations run:** 3 fix-and-sweep iterations (plus 2 extra confirmation sweeps). Final state: 3 consecutive full 8-round parallel sweeps (24 rounds) all clean at **71/71 passed**.

**Starting state:** 40 deterministic failures (8/8) out of 72 tests, driven by 2 upstream fixture bugs masquerading as ~40 independent failures (the TRIAGE-HINT pattern).

### Tests deleted (1)
- `test_cancel_invoiced_project_blocked_by_issued_invoice` (test_02_project_lifecycle.py) — **UNIQUE-DERIVABILITY / unreachable source-state collapse.** PRD §3.11 blocks cancel with `ERR_PROJECT_HAS_INVOICE` only when the project is `APPROVED`/`IN_PRODUCTION` with an `ISSUED`/`PAID` invoice. But PRD §3.8 says issuing an invoice atomically bubbles the project `DELIVERED → INVOICED` (and issue requires `DELIVERED`), so a project can never be in `APPROVED`/`IN_PRODUCTION` while an issued invoice exists. The error's source state is structurally unreachable; any faithful setup leaves the project `INVOICED`, from which cancel correctly returns the priority-5 `ERR_INVALID_STATE`. (Scaffold rule that drove it: `Corner/state_machines/cancel_invoiced_project_blocked_by_issued_invoice`.) Replaced with an explanatory comment block.

### Fixes applied to test_helpers/ (2)
- `fixtures.py` → `add_job()` — defaulted `bands=None` to `DEFAULT_BANDS` (weighted 1775) instead of `{}` (all-zero). The empty default caused `ERR_EMPTY_ANALYSIS` ("Quoted band words sum to zero") at quote time across 19 tests whose inline comments (`# default bands -> provisional 15975`) expected the canonical analyzed bands.
- `fixtures.py` → `setup_job_in_progress()` — changed the default reviewer window from `2026-06-01→06-02` (identical to the translator window, so it overlapped) to `2026-06-02→06-03` (touching the translator's end, which PRD §3.5 half-open semantics explicitly allow). The overlapping default caused `ERR_WINDOW_OVERLAP` across 21 tests.

### Fixes applied to test_suite/ (2)
- `test_04_assignment_matching.py` → `test_disjoint_day_throughput_accept_succeeds` — corrected the post-accept status assertion from `ACCEPTED` to `IN_PROGRESS`. PRD §3.5: "Once accepted, an assignment becomes `IN_PROGRESS` automatically as the job moves into active work"; a translator accept drives the job to `TRANSLATING`, so the accept response is `IN_PROGRESS`. (This is a more-faithful assertion, not a weakening — the impl already returns `IN_PROGRESS`, confirmed by reviewer-dependent QA tests.)
- `test_07_invoicing.py` → `_deliver_with_two_revision_rounds()` helper — assigned the created draft invoice to `ctx["invoice"]` (it was created but the result discarded), fixing the `KeyError: 'invoice'` in both `test_final_invoice_total_diverges_from_quote_with_revision_surcharge` and `test_final_invoice_revision_surcharge_component`. Verified the calc produces the exact asserted values (quote 39613, final total 44313, revision surcharge 2250).

### Fixes applied to implementation/ (1, infrastructure hardening only — no PRD-behavior change)
- `app.py` (+ `requirements.txt`, `start.sh`) — switched the WSGI server from Flask's dev server to **waitress** (multithreaded, production-grade), with a fallback to `app.run()` if waitress is absent. Under `--isolation per-test-server` at 8× concurrent load, the Flask dev server sporadically emitted `ConnectionResetError`/`BadStatusLine` during the kill-and-relaunch restart window (confirmed transient: the exact failing request returns a clean `403 ERR_FORBIDDEN_FOR_ROLE` against a healthy server, and the server never crashed). Waitress's cleaner connection teardown eliminated the flakiness — 24/24 rounds clean afterward. `start.sh`'s install guard now checks `import flask, waitress` so it still skips pip when both are present. No endpoints, fields, side effects, or data semantics were changed.
## Step 8: Finalize PRD — 2026-06-16T20:08:36.000Z

Step 8 ran (Step 7 made fixes: 1 deletion, 2 test_helpers, 2 test_suite, 1 implementation, so the skip condition was not met). Output workspace/PRD_FINALIZED.md was produced (264 lines, full document ending cleanly on the error-code catalogue; verified not truncated). The orchestrator process was signal-killed (exit 144, resource pressure) after the Step 8 subagent returned but before this entry was appended; entry reconstructed by supervisor. Step 9 resumes from PRD_FINALIZED.md.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-16T20:17:31.000Z

(Executed via in-session subagent after two standalone `claude -p` runs were signal-killed (exit 144, resource contention with a concurrent task_0381 pipeline) at this phase. The interrupted runs had left PRD_COMPLETED.md as a bare cp of PRD_FINALIZED.md; this pass redid Step 9 in full.)

**Line counts:** PRD_FINALIZED.md = 264 lines / 48,040 chars; PRD_COMPLETED.md = 264 lines / 50,745 chars. **Char delta: +2,705.** (Line count unchanged — every edit is an in-paragraph insert/revision; no new sections.)

**Counts:** 9 changes total — **6 ambiguity-pins**, **3 mismatch-revisions**.

- §2.3 Pagination — insert — ambiguity — out-of-range `limit` clamped to [1,100], negative `offset` clamped to 0 (not rejected); non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — services/helpers.py:40-56.
- §2.3 Ordering — insert — ambiguity — ascending-by-`created_at` ties broken by ascending `id` — services/helpers.py:61.
- §2.8 Concurrency tokens — insert — ambiguity — supplied token retained/echoed: `Assignment.expected_job_version` stored; `Invoice.expected_project_version` null on draft, set when issued — serializers.py:99,135; routes/invoices.py:31,108.
- §3.2 Job initial fields — insert — ambiguity — new job's four `actual_*_words` and `weighted_source_words` start null; `weighted_source_words` carried as float — routes/projects.py:200-204.
- §3.5 Throughput — insert — ambiguity — reviewer assignments count toward daily throughput using job quoted weighted words (payout 0); half-open shared-UTC-day rule — routes/assignments.py:52-69,204-208,247-268.
- §3.6 Submit-translation — revise — mismatch — `ERR_NO_REVIEWER_ASSIGNED` precondition enforced only on first submission out of TRANSLATING, not on REVISION resubmission — routes/jobs.py:59-65.
- §3.6 QA-report precondition — revise — mismatch — single combined `ERR_NO_REVIEWER_ASSIGNED` check; not-IN_QA → `ERR_INVALID_STATE`; unresolvable reviewer_assignment_id → `ERR_NOT_FOUND` — routes/qa_reports.py:34-54.
- §3.8 Draft invoice fields — insert — ambiguity — draft creation runs no precondition/calculation; six amount fields, `total_cents`, `expected_project_version` start null until issue — routes/invoices.py:21-35.
- §3.11 Cancel cascade — revise — mismatch — cancel only from DRAFT/QUOTED/APPROVED/IN_PRODUCTION (else `ERR_INVALID_STATE`); payout reversals for jobs in TRANSLATING/REVISION/IN_QA/QA_PASSED — routes/projects.py:153; services/workflow.py:31-43.

No remaining PRD silence or mismatch against implementation/ identified after the walk. Pipeline for task_0379 is COMPLETE: Steps 1–9 done; 71/71 tests pass across all 8 stability rounds.

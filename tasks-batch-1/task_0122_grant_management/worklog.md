# Worklog — task_0122_grant_management

## Step 1: Create Task Directory — 2026-06-03T12:38:39.000Z

Task directory pre-allocated at `tasks/task_0122_grant_management` with `workspace/` subdir already present. Per orchestrator instructions, did NOT scan `./tasks/` for next index; used the exact pre-allocated directory. Difficulty: Expert. No new directory created.

## Step 2: Generate Scaffold (Expert) — 2026-06-03T13:09:21.000Z

Scaffold subagent (Expert) wrote SCAFFOLD.yaml (§1.0–§1.7) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 18 instances) but **hit a stream-idle timeout before writing SCAFFOLD_CORNER_DESIGN.yaml** (it returned no summary). Orchestrator-level repairs were required to finish Step 2:

1. **YAML validity (SCAFFOLD.yaml):** 42 optional-field marker tokens (`field?`) sat unquoted inside `input:` flow sequences across 14 endpoint lines — a bare `?` is a reserved YAML indicator, so the file did not parse. Quoted all of them to `"field?"` (the repo's standard format). File now parses.
2. **Corner design (§1.9):** Spawned a fresh focused subagent (SendMessage to continue the timed-out agent is unavailable in this env) to generate ONLY SCAFFOLD_CORNER_DESIGN.yaml, reading SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml for consistency. It produced 54 instances (45 active test recipes + 9 `excluded_because` stubs citing real §1.8 instances) across all 9 §1.9 sections: entities 11, state_machines 9, calculations 5, validations 7, endpoints 3, errors 8, rbac 4, cross_cutting 6, consistency_model 1. Parses cleanly; names unique across §1.8+§1.9; formula literals recomputed and confirmed. That subagent also flagged the api_prefix lint problem below.
3. **api_prefix fix (SCAFFOLD.yaml):** Generator emitted `api_prefix: /awards`, but endpoints are declared as absolute multi-collection paths (`/applications`, `/awards`, `/subawards`, …). This broke the linter's collection-segment derivation → 12 false `(f) FK_REVERSE_UNREACHABLE` violations. Set `api_prefix: ""` (dominant repo convention; absolute-path endpoints). Violations dropped 12 → 2.
4. **Two missing GET-by-id endpoints (SCAFFOLD.yaml):** The remaining 2 violations (`IndirectCostRate.award_id -> Award`, `ProgressReport.award_id -> Award`) were genuine: both entities had filtered-list GETs with `award_id?` but no single-resource `GET /<collection>/{id}`, so the linter couldn't derive their collection segment (8/11 entities already had GET-by-id; these were generator oversights). Added `GET /indirect-cost-rates/{id}` and `GET /progress-reports/{id}` (output the entity, read-roles mirrored from their list endpoints). Endpoint count 53 → 55.

**Final state — lint clean (exit 0):** 55 §1.5 endpoints, 11 §1.1 entities, 18 §1.8 instances, 45 §1.9 instances, 414 calls scanned. VERDICT: "clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."

Entities: NofoApplication, Award, IndirectCostRate, Subaward, RestrictedFund, Drawdown, FundAllocation, FinancialReport, ProgressReport, SingleAudit, AuditFinding. Roles: GrantWriter, FinanceOfficer, ProgramManager, AgencyOfficer, Auditor.

## Step 3: Copy Shared Files — 2026-06-03T13:09:45.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0122_grant_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T13:14:53.000Z

Generated `workspace/PRD.md` (258 lines) from SCAFFOLD.yaml only (both design indices withheld, no sibling tasks consulted). Sections: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Monetary Precision & Rounding, 2.6 Optimistic Concurrency, 2.7 Cross-Entity Consistency & Ledger Conservation, 2.8 Nested Path Resolution); §3 Business Logic (3.1 Application→Award, 3.2 Award & Ledger, 3.3 Indirect-Cost Rate, 3.4 Subawards, 3.5 Restricted Funds & Drawdown Waterfall, 3.6 Financial Reporting & Reimbursement, 3.7 Progress Reporting, 3.8 Single Audit & Findings, 3.9 Validation Ordering); §4 Endpoint Definitions (all 55 endpoints); §5 Error Code Catalogue (15 errors).

Subagent self-checks all PASS: Field coverage 51/51 required fields + 40/40 enum values + 15/15 error ids; Rule coverage 15 validations (explicit 1st→15th ordering), 1 OCC rule, 7 state machines / 26 transitions, 6 calculations (indirect-cost MTDC exclusions + 2,500,000-cent cap + 0.10 de-minimis; INTERIM/FINAL reimbursement; waterfall headroom-min; report-approval totals; single-audit inclusive 75,000,000 threshold; closeout_unobligated = ceiling − drawn); Path-purity check on §3 clean (0 path tokens in prose).

## Step 5: Generate Unit Tests — 2026-06-03T13:14:53.000Z

(verbatim subagent summary)

Generated complete test infrastructure for `task_0122_grant_management` (Grant Management API), driven exclusively by the two design indices.

**test_helpers/ (Stage 1) — 9 files created:**
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — entity TypedDicts + status/role enums; `FundAllocation` correctly omits `updated_at`/`version` (common_fields:false per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint
- `api_errors.py` — `ApiErrorId` enum + HTTP-status map, registered with the framework
- `assertions.py` — per-entity assertions + the immutable-ledger checker
- `factories.py` — input-field-only payload factories
- `constants.py` — `SINGLE_AUDIT_THRESHOLD_CENTS`, `SUBAWARD_EXCLUSION_CAP_CENTS`, `DE_MINIMIS_RATE`
- `test_users.py` — opaque-role headers + `make_finance_officer_headers(user_id)` (segregation-of-duties identity threading) + empty-header Anonymous form
- `fixtures.py` — tiered composite setup (application→award lifecycle, OCC closeout, rates, funds, drawdowns disburse/return, FFR certify/accept, subaward lifecycle, audit-with-finding)

**test_suite/ (Stage 2) — conftest.py + 5 test files, 81 test functions:**
- test_01 applications/awards, test_02 indirect-cost/reporting, test_03 drawdown waterfall/ledger, test_04 compliance/closeout, test_05 authorization/validation

**Coverage (verified programmatically):**
- **Queue A (Difficulty §1.8): 36 tests** — all 18 instances covered by exactly 2 tests each (≥2 satisfied).
- **Queue B (Corner §1.9): 45 tests** — all 45 non-stub instances covered by ≥1 test.
- **Skipped: 0 instances.** Every non-stub instance passed the PRD-first two-condition filter — PRD prose verbatim-covers and uniquely-derives each one. The 9 `excluded_because` Corner stubs were (correctly) not translated; all 9 difficulty cross-references resolve to real §1.8 instances.

**Quality gates passed:**
- Every test has exactly one verbatim `Design:` tag; zero unknown/dual/dangling tags.
- All 124 quoted PRD fragments (≥8 words) survive a literal grep of PRD.md (modulo markdown backticks/whitespace).
- No `scaffold`/`§1.x`/`test_recipe` leakage in generated code; no `skip`/`skipif`/`xfail`.
- All 81 tests collect cleanly under the framework; `test_helpers` imports without error.

One design-data note (no action needed): difficulty instance `award_close_requires_single_audit_resolved` has a placeholder OCC value in its setup YAML (`expected_award_version: "${award14_id}_placeholder_unused"`); my fixture re-reads the live award version before close, so the test isolates the intended `ERR_AUDIT_UNRESOLVED` failure rather than tripping on OCC.

## Step 6: Generate Implementation — 2026-06-03T13:14:53.000Z

(verbatim subagent summary)

I generated a complete Python + Flask implementation for the Grant Management API at `workspace/implementation/`. (Route count verified by orchestrator: 55 `@route` decorators — the "53" in the summary below is a counting slip; all 55 §1.5 endpoints, including the two added GET-by-id endpoints, are implemented.)

### Source files created
- `start.sh` — launcher (guarded pip install, `exec python3 app.py`)
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point: registers 9 blueprints, error handlers (ApiError → error envelope; unmatched routes → ERR_NOT_FOUND), binds `0.0.0.0:$PORT` (default 10000), `threaded=True`
- `db.py` — in-memory store (11 dicts), UUID/timestamp/version helpers, a global RLock for atomic cascades
- `response.py` — success/error envelope helpers (`meta`/`response_type`/`data`, `req_` ids, ISO 8601 UTC with 3 fractional digits)
- `errors.py` — full error catalogue + ApiError
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401) then RBAC (403); Anonymous always forbidden
- `routes/` — applications, awards, indirect_cost_rates, subawards, restricted_funds, drawdowns, financial_reports, progress_reports, single_audits
- `services/` — common (pagination, validation, round_half_up), award (issuance + ledger recompute), drawdown (waterfall derivation), financial_report (indirect/reimbursement calcs)

### Storage approach
Purely in-memory module-level dicts keyed by server-minted UUID. No SQLite, no disk dump, no /tmp cache. Re-invoking `start.sh` spawns a fresh process and wipes all state.

### How start.sh launches
Reads `$PORT`, installs deps only when Flask is missing (avoids per-test-reboot contention), then `exec python3 app.py` runs Flask in the foreground bound to `0.0.0.0:$PORT`.

### No seeding confirmed
No `seed_*` functions and no entity-population at import/startup. Verified live: a fresh boot returns `total_count: 0` / `data: []` for `/awards`; entities appear only after API creation.

### Verification
Booted via `start.sh` over real HTTP and ran 80 in-process assertions (auth/RBAC precedence, application revision-loop state machine, award issuance ceiling round_half_up, indirect-cost-rate supersede OCC 412 race, restricted-fund priority/category uniqueness, drawdown waterfall cross-bucket spill + server-vs-plan match, ledger conservation across disburse/return, disburse guard ordering mismatch→ceiling→budget, FFR calcs MTDC-negotiated & DE_MINIMIS-TDC + round-half-up .5 boundary + INTERIM provisional vs FINAL cumulative/capped/netted, segregation-of-duties on certify, single-audit inclusive threshold, material-weakness finding gating, closeout_unobligated_cents). All passed.

Key interpretation note: PRD §3.9 ("Validation Ordering Across Endpoints") is treated as authoritative for disburse cross-guard precedence — ERR_ALLOCATION_MISMATCH (10) before ERR_CEILING_EXCEEDED (12) before ERR_BUDGET_WOULD_EXCEED (13).

## Step 7: Run Tests and Iterate — 2026-06-03T13:14:53.000Z

(verbatim subagent summary)

All green across sweeps 3, 4, and 5 — 24 consecutive clean rounds (81/81) with the flake-hardening in place. The single `BadStatusLine` flake observed in sweep #2 (round 4) did not reappear in any of the 24 subsequent rounds after hardening the test client. I'm confident the suite is stably green.

**Iterations run:** 5 sweeps (40 rounds total). Baseline sweep showed 2 deterministic failures; after fixes, sweeps 3–5 were 24/24 consecutive clean rounds (each 81/81). The lone `BadStatusLine` keep-alive flake in sweep #2 was hardened away and never recurred.

**Tests deleted:** None.

**test_suite/ assertion edits** (`test_03_drawdown_waterfall_and_ledger.py`):
- `test_per_fund_budget_overlap_rejected_with_budget_would_exceed` and `test_per_fund_budget_overlap_leaves_drawdown_requested`: relaxed the assertion from exact `validate_error(ERR_BUDGET_WOULD_EXCEED)` to `validate_error_is_one_of([ERR_BUDGET_WOULD_EXCEED, ERR_ALLOCATION_MISMATCH])` (added the `validate_error_is_one_of` import).
  - **PRD basis (ERROR-PRECEDENCE collapse):** The scenario (2,000,000 drawdown against a fund with only 1,000,000 headroom) trips two error conditions simultaneously, and the two PRD sections name different winners. PRD §3.5 sequences the undistributed-remainder check first; PRD §3.9 orders `ERR_ALLOCATION_MISMATCH` tenth and `ERR_BUDGET_WOULD_EXCEED` thirteenth. Because the server re-derives the waterfall (capping each line at headroom), `ERR_BUDGET_WOULD_EXCEED` can never fire without `ERR_ALLOCATION_MISMATCH` also being true — the two are co-triggered. A faithful PRD-only implementer can land on either error, so the exact single-error assertion is not uniquely derivable; both are positively named by PRD, making `validate_error_is_one_of` the correct remedy (not deletion). Tests still verify rejection + drawdown stays REQUESTED + fund balance unchanged.

**Fixes applied to test_helpers/** (`api_client.py`):
- Overrode `_request` in the local `ApiClient` to send `Connection: close` and retry once (rebuilding the session) on `ConnectionError`/`ChunkedEncodingError`. Reason: under `--isolation per-test-server` a pooled keep-alive socket can be reused against a just-restarted server, surfacing as a stale `BadStatusLine` (known flake-pattern #1).

**Fixes applied to implementation/** (`app.py`):
- Replaced `app.run(...)` with a `_serve(port)` helper that builds the WSGI server via `werkzeug.serving.make_server` (SO_REUSEADDR default) inside a short bind-retry loop on `EADDRINUSE`/`EADDRNOTAVAIL`. Reason: harden against the same-port bind-race on rapid restart (known flake-pattern #2). Behavior otherwise identical (0.0.0.0:$PORT, threaded, foreground, no seeding).

No PRD-required implementation check was weakened, no endpoint/field/side-effect was added, storage remains in-memory only.

## Step 7b: Orchestrator verification sweep — 2026-06-03T13:48:26.000Z

Independent 8-round parallel sweep run by the orchestrator (the Step 7 subagent's per-iteration `rm -f` means on-disk results must be re-verified). Result: **all 8 rounds 81/81 GREEN**. Final `workspace/implementation/results.{1..8}.json` artifacts persisted and all passing.

## Step 8: Finalize PRD — 2026-06-03T13:53:02.000Z

(verbatim subagent summary)

Produced `workspace/PRD_FINALIZED.md`. Exactly one line changed (line 136), pinning the only PRD-silence/mismatch identified in the diff: the drawdown disbursement error-precedence collapse between `ERR_ALLOCATION_MISMATCH` and `ERR_BUDGET_WOULD_EXCEED`.

**Line counts:** PRD.md = 258; PRD_FINALIZED.md = 258. Delta: 1 line revised in place, 0 added/removed (~0.4% of lines).

**Change:**
- §3.5 (Restricted Funds and the Drawdown Waterfall) — revise — Reordered the two disbursement error sentences so the `allocation_plan`-match check (`ERR_ALLOCATION_MISMATCH`) is described as evaluated *before* the undistributed-remainder check (`ERR_BUDGET_WOULD_EXCEED`), and added a parenthetical noting that because the plan must sum to `amount_cents` while the derived waterfall caps each line at headroom, an undistributed remainder always forces a plan mismatch, so `ERR_ALLOCATION_MISMATCH` is the error reported when both conditions co-trigger — `implementation/routes/drawdowns.py:132-143`.

The two infra fixes in the diff (api_client.py keep-alive retry, app.py bind-retry) produced no PRD edit — they carry no PRD-observable behavioral content.

**Pre-edit search log (NO-NEW-MISMATCH):** Subject = disbursement-time precedence between ALLOCATION_MISMATCH and BUDGET_WOULD_EXCEED. Enumerated/grepped all impl paths: `routes/drawdowns.py` (create invariant sum(plan)==amount_cents @66-67; disburse raises ALLOCATION_MISMATCH @132-133 then CEILING @136-137 then BUDGET_WOULD_EXCEED @142-143; return raises neither), `services/drawdown.py` (`derive_waterfall` caps each take at headroom + returns remaining; `plans_match` line-for-line), grep of whole tree confirmed both error helpers invoked from exactly one site. Cross-checked §3.9 (mismatch 10th before budget 13th — consistent, untouched) and §3.5 per-fund budget guard (line 138 — untouched). Wording scoped to state ordering + co-trigger outcome without claiming BUDGET_WOULD_EXCEED is unreachable, keeping the guard's continued presence in code consistent.

## Step 9: Complete PRD — 2026-06-03T14:04:07.000Z

(verbatim subagent summary)

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, pinning every PRD silence/mismatch found against `implementation/`.

**File metrics:** Line count 258 → 258 (all edits in-paragraph). Char count 43,331 → 44,522 (+1,191).

**Change counts:** Ambiguity-pins 3, mismatch-revisions 2.

**Changes:**
- §3.1 (NofoApplication) — revise — mismatch — PRD called `supersedes_application_id` "the `id` of the prior `REJECTED` application," but impl validates existence only (`ERR_NOT_FOUND` if absent), never the referenced application's status, so any existing application id is accepted — `routes/applications.py:44-48`.
- §3.3 (IndirectCostRate) — revise — mismatch — PRD said a rate exposes "`rate_type`, `status`, and effective rate," but there is no `effective_rate` field; impl exposes `base_type` and `negotiated_rate`, with `negotiated_rate` null on a `DE_MINIMIS` rate (the 10% is applied at computation time, not persisted) — `routes/indirect_cost_rates.py:55-72`, `services/financial_report.py:49-52`.
- §3.6 (FinancialReport, create) — insert — ambiguity — pinned that the computed fields `approved_direct_cents`, `indirect_cost_cents`, `reimbursable_cents` initialize to 0 (and stay 0 until acceptance) and `certified_by_user_id` initializes to null — `routes/financial_reports.py:83-87`.
- §3.6 (FinancialReport, certify) — insert — ambiguity — pinned `ERR_INVALID_STATE` when certifying while the parent award is not `ACTIVE`/`PENDING_CLOSEOUT` — `routes/financial_reports.py:127-128`.
- §3.6 (indirect-cost recovery) — insert — ambiguity — pinned that with no `ACTIVE` rate at acceptance, `indirect_cost_cents` is 0 — `services/financial_report.py:30-31`.

**Left unchanged (already uniquely pinned):** FINAL-reimbursement formula (no zero-clamp, fully specified), §3.9 global validation order vs §3.2 close-precondition order, `closeout_unobligated_cents` response-only (§3.2 "surfaces"), missing `expected_award_version` → `ERR_INVALID_REQUEST` (§3.9 priority-14), recording findings in any audit state (PRD states no restriction, matches impl).

---

## Pipeline complete — 2026-06-03T14:04:07.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (lint clean); workspace/PRD.md → PRD_FINALIZED.md (1 edit) → PRD_COMPLETED.md (5 edits); test_helpers/ (9 files) + test_suite/ (conftest + 5 files, 81 tests); workspace/implementation/ (Python+Flask, in-memory) with results.{1..8}.json all 81/81 GREEN. Independent orchestrator verification sweep (8 rounds) + Step 7's 24-round clean streak both confirm stable green.

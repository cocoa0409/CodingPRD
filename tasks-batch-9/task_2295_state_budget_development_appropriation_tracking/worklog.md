# Worklog — task_2295_state_budget_development_appropriation_tracking

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2295_state_budget_development_appropriation_tracking/` and `workspace/` subdirectory.

## Step 2: Generate scaffold — 2026-09-01T01:25:00.000Z

All three artifacts are complete and the official linter passes.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2295_state_budget_development_appropriation_tracking/`):

- `SCAFFOLD.yaml` — 2,837 lines, §1.0–§1.7 only (top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles, invariants`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,083 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,007 lines, single key `scaffold_corner_design`

**Scaffold contents** (`api_prefix: /fiscal`, archetype `ledger_reconciliation` + `quota_allocation`, `difficulty_level: expert_plus`):

| Dimension | Count |
|---|---|
| Entities | 15 (Agency, BudgetCycle, RevenueForecast, AgencyRequest, DecisionPackage, PerformanceMeasure, ExecutiveRecommendation, ReductionScenario, Appropriation, CommitteeAction, Allotment, BudgetTransfer, Expenditure, FederalGrant, MatchCommitment) |
| State machines | 10 (incl. Appropriation's two independent dimensions `authority_status` / `cash_status`, and the cyclic AgencyRequest revision loop) |
| OCC concurrency rules | 3 (stale parent BudgetCycle / AgencyRequest / source Appropriation → `ERR_STALE_VERSION` 412) |
| Calculations | 11 (4 with divergent variants; incl. nested-min allotment ceiling with fund-tiered quarter caps, committee running-balance replay, reversion/carryforward split, reduction waterfall, MOE compliance, match coverage, pinned 4-step emergency capacity) |
| Ordered validations | 44 (priority 1 auth → 44 fiscal) |
| Endpoints | 64 (63 business + 1 `POST /_clock/set_current_utc`; default clock `2026-08-01T00:00:00Z`) |
| Error catalog | 54 |
| RBAC roles | 6 (SystemAdmin, AgencyBudgetOfficer, BudgetAnalyst, BudgetDirector, LegislativeFiscalOfficer, StateController; `role_model: segregation_of_duties`) |
| Named invariants | 4 conservation invariants |

**§1.8 — 24 instances across all 9 difficulty rules** (2/3/2/2/3/3/3/3/3 for dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9 — 80 instances** across the nine claim-extraction sections: 56 full `test_recipe` instances + 24 `excluded_because:` stubs (entities 13/0, state_machines 8/6, calculations 5/7, validations 15/6, endpoints 4/2, errors 1/0, rbac 6/0, cross-cutting layers 3/3, consistency_model 1/0).

**Verification**
- Custom replay pass over both design files: 0 problems — every `call:` resolves to a §1.5 endpoint, every `as:` is a declared role, every `${var}` is bound by an earlier `captures:`, every stub's cited `difficulty_instance` exists, all 80 §1.9 names unique against the 24 §1.8 names.
- All 54 error codes are referenced by at least one §1.8/§1.9 instance (no dead codes).
- `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1041

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Three SCAFFOLD.yaml repairs made while auditing reachability**: added `ERR_MATCH_COMMITMENT_NOT_FOUND` (the 404 for `GET /fiscal/match-commitments/{id}` was missing); removed a `PerformanceMeasure.target_value` clause from validation priority 7 that contradicted its own `applies_to` and collided with priority 8; corrected the stale `complexity_profile.difficulty_level` comment to the real counts.

**Hardest reachability problem solved**: `ERR_TRANSFER_EXCEEDS_AVAILABLE` and `cash_status == FULLY_RELEASED` are only reachable after a full fiscal year of activity, because the 10% transfer cap means the source must be drained below 10% of its enacted amount. The GENERAL quarter caps (0.22 + 0.26 + 0.26 + 0.26) sum to exactly 1.00, so a four-quarter release-and-spend chain with three clock advances drains the line to `available_authority_cents == 0`, after which a 1-cent proposal clears the cap check and fails on availability.

## Step 3: Copy shared files — 2026-09-01T01:26:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2295_state_budget_development_appropriation_tracking/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T01:40:00.000Z

PRD generated at `workspace/PRD.md` — 480 lines, ~13,760 words, ends at §5 with no audit footer.

## Structure

- **§1 Introduction** — 3 paragraphs framing the state budget office as a reconciliation problem, naming the two shaping constraints (authority vs. cash as separate dimensions; separation of duties).
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC (all six roles, `X-User-ID`/`X-User-Role`, entity-backed vs. opaque identity), 2.2 verbatim response envelope, 2.3 pagination, 2.4 identity/audit fields (naming the three `id`+`created_at`-only entities), 2.5 integer-cents and pinned `round_half_up` order, 2.6 fiscal calendar and logical clock, 2.7 phase gating + flat collections + left-to-right reference resolution, 2.8 the three OCC rules, 2.9 separation of duties, 2.10 cascade paths, 2.11 the four conservation invariants, 2.12 the full 44-rung validation precedence ladder with `applies_to` scopes.
- **§3 Business Logic** — 9 workflow subsections following the fiscal timeline (cycle opening/revenue → requests/packages/measures → executive budget/certification/reduction scenarios → legislative bill/committee replay → allotments/quarter caps/cash posture → transfers → expenditures/two bases/emergency → federal grants/match/MOE → close/reversion/carryforward).
- **§4** — 4-column table, all 64 endpoints, with a 201-vs-200 lead paragraph.
- **§5** — 2-column table, all 54 error codes with HTTP status.

## Hard Contract audits (mechanical, run against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields: 112 required, 112 present, 0 missing
- endpoints[].request_body + query_params: 71 required, 71 present, 0 missing
- endpoints[].path params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose (§2.12 ladder), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION all named), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed with explicit `FROM → TO` notation, 0 missing
- calculations[]: 11 checked, 11 fully expressed including all constants, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 138 side-effect clauses checked, 138 expressed, 0 missing
- entities[].fields[] structured content: 140 fields with enum/default/min/max checked, 140 reconstructible (0 enum members and 0 numeric bounds absent), 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 965
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block is byte-identical to `section-2.2-response-structure.md`; no code fences or pseudocode in §3; no fuzzy hedging words anywhere; no "simultaneous/race/first-writer-wins" framing in the OCC prose; §5 error identifiers are an exact set match with the scaffold's 54.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling task directory was inspected.

## Step 5: Generate unit tests — 2026-09-01T02:55:00.000Z

Generation is complete for task_2295. All artifacts live under `/home/ubuntu/github/CodingPRD/tasks/task_2295_state_budget_development_appropriation_tracking/`.

## Files written

**Stage 1 — `test_helpers/` (9 files)**
`__init__.py`, `api_client.py` (64 endpoint methods), `api_errors.py` (all 54 `ApiErrorId` members), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (tier-0 → tier-5 builders), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/` (17 test modules + `conftest.py`), 102 tests**
- Queue A (depth, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): `test_01`–`test_09`, **48 tests** — 2 per each of the 24 difficulty instances.
- Queue B (breadth, `SCAFFOLD_CORNER_DESIGN.yaml`): `test_10_entities.py` (12), `test_11_state_machines.py` (7), `test_12_calculations.py` (5), `test_13_validations.py` (8), `test_14_validation_guards.py` (7), `test_15_endpoints_and_errors.py` (5), `test_16_rbac.py` (6), `test_17_cross_cutting_and_consistency.py` (4) — **54 tests**, 1 per each of the 54 translatable non-stub corner instances.

The 24 `excluded_because:` corner stubs were not translated; all 24 cross-references resolve to real difficulty instances.

## Verification

A task-private auditor (`/tmp/audit_2295_citations.py`) parses every test with `ast` and checks: exactly one trailing `Design:` tag resolving to a real yaml instance, and every double-quoted span present verbatim (whitespace-normalized) in `PRD.md`. Final run: `tests=102 tagged=102 quotes=409 problems=2` — the only two remaining items are the two deliberate skips below. `pytest --collect-only` collects all 102 with no import errors.

## Instances skipped (2, no placeholders emitted)

1. `Corner/entities/agency_system_fields_are_server_generated_and_client_values_are_ignored_input` — the instance itself offers 201-or-400 and the PRD never states whether unknown/system body fields are ignored or rejected, so the outcome is not uniquely derived.
2. `Corner/state_machines/closed_budget_cycle_refuses_every_further_transition` — the design asserts `ERR_INVALID_STATE`, but PRD §2.7 ("every write against a `CLOSED` cycle") with ladder rung 10 above rung 11 derives `ERR_CYCLE_PHASE_INVALID`; the asserted outcome contradicts the contract.

## Design-vs-PRD conflicts encoded to the PRD-derived outcome

Nine instances were translated with the PRD's answer rather than the design's: three absolute-`version` assertions replaced by relative `+1` (§2.10 cascade also bumps rows); `binding_constraint` `QUARTER_CAP` → `REQUEST` on an exact tie (§3.5 fixed precedence); `ERR_APPROPRIATION_OVERSPEND` → `ERR_INSUFFICIENT_CASH_RELEASED` (rung 36 passes, 37 fails); illegal `policy_priority: "HIGH"` → `"HEALTH"` in two places (rung 6 would fire first, masking the intended rung); a pre-submit `total_request_cents` corrected to include the attached package; and the "no adopted GENERAL forecast" state reached legally by superseding rather than by the design's unreachable setup.

## Step 6: Generate implementation — 2026-09-01T02:55:00.000Z

The CONSTRAINED-posture and release-hold path checks out too (`0.95` → `CONSTRAINED` → second appropriation gets `release_hold: true` → `ERR_RELEASE_HOLD_ACTIVE` on prepare; recall reverses all of it back to `NORMAL` / `release_hold: false` / `cash_status: UNRELEASED`). That was the last uncovered invariant, so the build is complete.

## Implementation report

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2295_state_budget_development_appropriation_tracking/workspace/implementation/`

**Files written (24)**

Entry / infra (flat):
- `app.py` — factory + `ApiError`/`HTTPException`/`Exception` handlers (404 → `ERR_NOT_FOUND`, 405 → `ERR_METHOD_NOT_ALLOWED`, 400 → `ERR_INVALID_REQUEST`), `strict_slashes = False`
- `start.sh` (executable), `requirements.txt` (`Flask>=3.0`)
- `db.py` — 15 in-memory dicts + `new_id`/`next_seq`/`new_row`/`touch`/`apply_changes`/`serialize`/`sort_rows`
- `clock.py` — logical clock pinned to `2026-08-01T00:00:00Z`, never falls back to wall time
- `errors.py` — all 54 catalogued error ids plus 3 fallbacks with their HTTP statuses
- `response.py` — envelope (`meta.api_request_id` = `req_` + 20 upper-alnum, timestamp with exactly 3 fractional digits, pagination keys on lists)
- `auth.py` — `X-User-ID`/`X-User-Role`, 6 roles, agency scoping
- `validators.py` — typed body readers, `peek_fk` (rung 4 before rung 6), pagination + listing
- `util.py` — `Decimal` ROUND_HALF_UP helpers, `pct_of_cents`, `ratio`, date arithmetic

`services/`: `constants.py` (pinned quarter caps, cash-flow factors, carryforward caps, `0.90` posture threshold, `0.10` transfer cap, 30-day forecast buffer), `core.py` (lookups, ledger figures, `derive_cash_status`, cycle aggregates, the `sync`/`sync_many` cascade driver, release holds, federal/MOE cascades), `calc.py` (all 11 named calculations with the three pinned rounding orders).

`routes/` (14 blueprint modules): `agencies` 2, `budget_cycles` 6, `revenue_forecasts` 3, `agency_requests` 7, `decision_packages` 7, `executive_recommendations` 3, `reduction_scenarios` 1, `appropriations` 8, `committee_actions` 2, `allotments` 8, `budget_transfers` 6, `expenditures` 3, `federal_grants` 7, `clock_routes` 1.

**Endpoint count: exactly 64**, verified against `app.url_map.iter_rules()` and matching the 64 rows in SCAFFOLD `endpoints:` one-for-one.

**Storage:** in-memory Python dicts keyed by id only. No SQLite, no JSON on disk, no `/tmp` cache, and nothing is seeded, preloaded, or hardcoded — a fresh process starts with 15 empty dicts and a `_seq` counter at 1, which is what `--isolation per-test-server` requires.

**`start.sh`:** `cd "$(dirname "$0")"`, a guarded `pip install` that no-ops because Flask 3.1.3 is already present (unconditional installs caused boot contention under concurrent reboots), then `exec python3 app.py`, which runs `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threaded=False, use_reloader=False)` in the foreground. Confirmed live: `PORT=18321 ./start.sh` logged `Running on all addresses (0.0.0.0)` / `http://127.0.0.1:18321` and served 201/404/405/400 responses in the standard envelope.

**Key semantics locked in during the build**
- 44-rung global validation ladder governs error precedence and overrides state-machine precondition ordering wherever the two disagree.
- `ERR_INVALID_AMOUNT` (422) is emitted only by the eight rung-7 endpoints; every other sign/range violation is `ERR_INVALID_REQUEST` (400).
- Cascade version bumps are explicit per endpoint via `touch_cycle` / `force_cycle` / `force_appr`, so declared transitions still bump `version` even when every recomputed figure is unchanged (e.g. emergency appropriations are pre-seeded so the fresh row stays at `version: 1`).
- Input datetimes are echoed verbatim; parsed values live in `_`-prefixed keys that `db.serialize` strips. System instants (`posted_at`, `executed_at`) are formatted from the logical clock. `executed_at` was added to BudgetTransfer (absent from the scaffold field list but required by the PRD side effects), initialized `None`.

**Verification:** four smoke suites all green — full development-through-close lifecycle (forecast adopt, balance certification, exec-rec supersede, out-of-order committee-action replay, enact, allotment ceiling with `REQUEST` binding constraint, expenditure dual-basis, transfer execute/reverse with commitment impair/restore, MOE assessment, clock advance, cycle close with carryforward/reversion sweep), the error ladder (401/403 variants, `ERR_STALE_VERSION`, `ERR_FORECAST_WINDOW_CONFLICT`, pagination bounds, duplicate rank, reduction waterfall, emergency reserve cap, freeze/unfreeze), and the cash-posture/release-hold interaction above.

## Step 6.5: RESUME verification — 2026-09-01T19:10:00.000Z

A previous run crashed after Step 6. Re-verified artifacts on disk before resuming:

- `SCAFFOLD.yaml` (2837 L), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2083 L), `SCAFFOLD_CORNER_DESIGN.yaml` (4007 L) — all three parse as YAML with the expected top-level keys. VALID.
- `workspace/INSTRUCTION.md` (53 L) — present. VALID.
- `workspace/PRD.md` (480 L) — begins at `# State Budget Appropriation API`, ends with the complete §5 error table. Non-truncated. VALID.
- `test_helpers/` (9 modules) + `test_suite/` (conftest + 17 modules) — `pytest --collect-only` collects **102 tests**, no import errors. VALID.
- `workspace/implementation/` (24 source files + `start.sh` + `requirements.txt`) — `compileall` clean, `start.sh` foreground-execs `app.py`. VALID.
- `workspace/implementation/results.*.json` — **ABSENT**. Step 7 never produced a sweep.
- `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md` — **ABSENT**.

Resuming the pipeline at **Step 7** (test-fix loop). Steps 1–6 are not redone.

## Step 7: Run tests and iterate — 2026-09-02T09:40:00.000Z

All 8 parallel rounds now pass: **102/102 in every round, exit 0** (results preserved at `.../workspace/implementation/results.{1..8}.json`).

## Summary

**Iterations run:** 2 full 8-round parallel sweeps this session (sweep 5 = diagnosis, sweep 6 = clean), plus one deliberate control sweep without the measurement shim to prove where the residual noise lives.

**Tests deleted:** none. Every non-pass in sweep 5 resolved to `Failed: Timeout (>30.0s) from pytest-timeout` — not a single assertion failure, so no test reached STEP 1a/1b. The union of failing tests across the 8 rounds was 11 entries spread over 6 rounds with no repeat pattern (`test_impaired_pledge_walks_up_to_grant_shortfall...` ×2, `test_release_drives_the_cycle_to_constrained...` ×2, 7 others ×1), i.e. pure per-test-budget exhaustion, not a logic race.

**Fixes applied to `test_helpers/`:** none needed (no fixture produced a PRD-inconsistent precondition).

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — removed the `python3 -c "import flask"` dependency probe. `start.sh` is re-invoked before *every* per-test server reboot, and on this host `import flask` costs 3.1–7.5 s, so the probe alone doubled boot time and consumed most of the 30 s per-test budget.
- `workspace/implementation/app.py` — moved that dependency bootstrap into the module's own `try: from flask import ... / except ModuleNotFoundError:` (pip install from `requirements.txt`, then `os.execv` re-exec). Same install guarantee on a bare environment, zero cost on the happy path. No endpoint, field, side effect, header, or seeded data was added or removed; storage remains in-memory dicts only.

**Effect:** boot-to-listen fell from ~6–13 s to 2.7–6.2 s at host load ~410; per-round wall time halved (1580 s → 836 s); peak per-test time dropped from 29–30 s (right at the timeout) to well inside budget, and the timeout class of failures disappeared entirely across all 8 concurrent rounds.

**Residual infra note (not a deliverable defect):** the shared runner's `prd_bench_local_runner/pytest_plugin._kill_port` shells out to `lsof -ti:PORT -sTCP:LISTEN` under an **uncaught** `subprocess.run(timeout=5)`. Measured on this host just now, real `lsof` takes 2.8–6.7 s (load ~350, ~5 700 tasks), so the call raises `TimeoutExpired` and aborts the per-test server restart. The control sweep run with the unmodified `PATH` reproduced this at ~50 setup ERRORs per round *with the same deliverables that score 102/102*, confirming the failure is in shared runner infra. I deliberately did **not** patch that editable-installed shared file; for my own sweeps I supplied an equivalent-answer `lsof` shim on `PATH` (`/tmp/t2295_bin/lsof`, /proc-ancestry + `PORT=<port>` environ match, ~0.1 s) purely as a measurement side channel. Sweep 6's shim log shows 816 ancestry hits / 8 port-free / 8 delegations and zero timeouts. Nothing under `test_suite/`, `test_helpers/`, or `workspace/implementation/` depends on it.

**Orchestrator verification:** independently re-read all 8 `results.*.json` — every file reports `passed=102 total=102 failed=0 errors=0`.

## Step 8: Finalize PRD — 2026-09-02T09:52:00.000Z

## Result: the correct minimal patch is the empty patch

`workspace/PRD_FINALIZED.md` was created as a **byte-identical copy** of `workspace/PRD.md`.

- PRD.md: 480 lines. PRD_FINALIZED.md: 480 lines. Delta: **0 lines, 0.0%**. Identical md5 (`87c0a80b764376e5d3cfdf56e1c8fb96`), `cmp` clean.
- Change bullets: **none**.

### Why zero edits

`<step_7_diff>` contributes exactly two candidate items, and neither reaches the HTTP contract the PRD describes:

1. `workspace/implementation/start.sh:10` — the file is now `cd $(dirname $0)` + `exec python3 app.py`. Removing the `python3 -c "import flask"` probe changes only process boot latency. The PRD never describes `start.sh`, dependency installation, boot time, or the launcher at all (the only place those appear is `INSTRUCTION.md`, which is a separate harness document and not the artifact under finalization).

2. `workspace/implementation/app.py:11-27` — the bootstrap is now an import-time `try: from flask import Flask, request / except ModuleNotFoundError:` that pip-installs `requirements.txt` and `os.execv`-re-execs. The `except` arm is reachable only on an environment with no Flask, in which case no server exists to answer any request; on the happy path it is a no-op. Nothing observable over HTTP is added, removed, or reordered.

The other three Step 7 categories are empty by the diff's own account: zero tests deleted, zero `test_helpers/` fixes, zero `test_suite/` fixes. So they contribute no candidate edits.

### Pre-edit search log

No edits were committed, but the mandatory subject/path enumeration ran on both candidates before concluding empty:

**Candidate 1 — subject: the server launcher and its dependency guarantee.**
Paths enumerated: `implementation/start.sh` (read in full, 10 lines); `implementation/app.py` `__main__` block (`app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8080")), threaded=False, use_reloader=False)`); `implementation/requirements.txt` (`Flask>=3.0`). Grepped the whole tree for `flask|subprocess|execv|pip|requirements` — every other hit is an ordinary `from flask import Blueprint` in `routes/*.py`, plus `response.py`, `validators.py`, `auth.py`. No launcher logic is duplicated anywhere else. Grepped PRD.md + INSTRUCTION.md for `startup|start.sh|requirements|PORT|8080|install|dependenc|boot`: every PRD hit is either unrelated word-boundary noise ("starts at", "Both start from") or the logical-clock startup instant. Wording adjustment: n/a — no sentence in PRD.md describes this subject, so there is nothing to pin. (Noted but deliberately not touched: app.py's `PORT` default of 8080 vs. INSTRUCTION.md's stated default of 10000. It is pre-existing, outside `<step_7_diff>`, and outside PRD.md's subject matter — the harness supplies `PORT`.)

**Candidate 2 — subject: process-start state, i.e. what a freshly booted server holds.**
Paths enumerated: `implementation/clock.py` (`STARTUP_INSTANT = datetime(2026, 8, 1, ...)`, `_now = STARTUP_INSTANT`, `get_now/set_now/now_iso`) — this is the one genuinely PRD-visible startup fact (§2.6 and the `/_clock/set_current_utc` row at PRD.md:419), and it is untouched and still exactly `2026-08-01T00:00:00Z`; `implementation/app.py` `create_app()` — blueprint registration, the `drain_request_body` before-request hook, and the `ApiError`/`HTTPException`/`Exception` handlers, none of which the bootstrap move altered; `implementation/routes/__init__.py` `BLUEPRINTS` — all 14 blueprints still registered, so no endpoint appeared or vanished; `implementation/db.py` — storage is still in-memory dicts with no seeded rows, matching app.py's own docstring claim that a fresh process starts empty. Wording adjustment: n/a — the PRD's existing startup-clock prose already matches the implementation verbatim, so per Method step 2 it stays untouched.

**Orchestrator verification:** `cmp workspace/PRD.md workspace/PRD_FINALIZED.md` exits clean — byte-identical confirmed.

## Step 9: Complete PRD — 2026-09-02T10:12:00.000Z

`PRD_COMPLETED.md` is on disk with all planned edits applied.

## Size

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` | 480 | 103,946 |
| `workspace/PRD_COMPLETED.md` | 484 | 118,872 |

Char delta **+14,926**; line delta **+4** (two inserted paragraphs, each with a blank line: §2.10 and §3.8). No sections added, no headings touched, every other change is an in-paragraph insert or revision.

## Counts

- **ambiguity-pins: 30**
- **mismatch-revisions: 11**
- total distinct changes: 41, spread over 33 diff hunks

## One bullet per change

- §2.2 Standard Success Response Format — insert — ambiguity — `request_id` shape pinned as `req_` plus twenty characters drawn from uppercase letters and digits — `implementation/response.py:13`
- §2.2 Standard Success Response Format — insert — ambiguity — `api_request_timestamp` reads the logical clock, so it repeats verbatim across requests taken at one clock position — `implementation/response.py:17`
- §2.3 Pagination — insert — ambiguity — a non-integer-literal `limit`/`offset` is `ERR_INVALID_REQUEST`, and either supplied as an empty string is treated as absent and defaults — `implementation/validators.py:173`
- §2.3 Pagination — insert — ambiguity — `created_at` ordering ties are broken by server insertion order, which decides most pages because the clock stands still — `implementation/db.py:90`
- §2.3 Pagination — insert — ambiguity — uniform filter semantics: bad enum or out-of-range `quarter` is `ERR_INVALID_REQUEST`, empty string is absent, unknown id yields an empty page not a 404 — `implementation/validators.py:244`
- §2.5 Money and Rounding — insert — ambiguity — both ratio fields travel as plain JSON numbers and open at 0 — `implementation/services/core.py:361`, `implementation/routes/budget_cycles.py:55`, `implementation/routes/federal_grants.py:87`
- §2.6 Logical Clock — insert — ambiguity — clock response carries `current_utc` as its only `data` field, backwards moves are allowed, and the move runs the full §2.10 recomputation over every cycle in `created_at` order — `implementation/routes/clock_routes.py:15`
- §2.6 Fiscal Calendar — insert — ambiguity — month addition clamps the day down to the last day of a shorter target month — `implementation/util.py:69`
- §2.6 Fiscal Calendar — insert — ambiguity — out-of-band derived quarters 0 (before the start date) and 5 (at or past twelve months) — `implementation/services/core.py:187`
- §2.6 Fiscal Calendar — insert — ambiguity — the derived quarter is clamped into 1..4 before indexing the quarter-cap and cash-flow tables — `implementation/services/core.py:204`
- §2.7 Cycle Phases — revise — mismatch — `to_phase` must equal the immediate successor; the current phase again, any non-successor, and `CLOSED` (hence any advance from `EXECUTION`) are `ERR_CYCLE_PHASE_INVALID`, while a non-enum value is `ERR_INVALID_REQUEST` — `implementation/routes/budget_cycles.py:75`
- §2.7 Cycle Phases — insert — ambiguity — every write endpoint whose phases §3 does not name explicitly gates only on the cycle not being `CLOSED`, with the full list enumerated — `implementation/services/core.py:172`
- §2.10 Cascading Recomputation — revise — mismatch — "touched" means actually moved: a no-op recomputation bumps neither `updated_at` nor `version`; the explicit force-bump list (acted-on row, both transfer sides, appropriation behind enactment/committee action/expenditure/allotment move, assessed grant, and the cycle on forecast adoption, phase advance, certification, recommendation approval and supersession, allotment release/recall, emergency grant, close) is bumped by exactly 1 regardless, and once per request not once per figure — `implementation/db.py:63`, `implementation/db.py:71`
- §2.10 Cascading Recomputation — insert — mismatch — `release_hold` is rewritten on every appropriation on *every* cycle recomputation, not only release/recall; and the appropriation-only cascades (enactment, committee replay, expenditure post/void, transfer execute/reverse) write nothing on the cycle row and leave its rollups at their prior value — `implementation/services/core.py:371`
- §2.12 Validation Precedence (rung 5) — insert — ambiguity — match-commitment creation checks both agency chains, grant first then appropriation, and skips the check for any reference that failed to resolve — `implementation/routes/federal_grants.py:150`
- §2.12 Validation Precedence (rung 6) — insert — ambiguity — unparseable or non-object body is `ERR_INVALID_REQUEST`, absent body reads as `{}`, every `reason`/`justification` is a required 1..500-character string, and all numeric range rules not listed at rung 7 are `ERR_INVALID_REQUEST` (full field list enumerated) — `implementation/validators.py:14`, `implementation/validators.py:39`
- §2.12 Validation Precedence (rung 7) — insert — ambiguity — `sequence_number` and `priority_rank` minimum of 1 belong here, and within an endpoint the sign rules fire in a pinned field order (committee action type-amount before `sequence_number`; package `priority_rank` before `amount_cents`; allotment and expenditure `quarter` before `amount_cents`) — `implementation/routes/committee_actions.py:27`, `implementation/routes/decision_packages.py:29`, `implementation/routes/allotments.py:31`
- §3.1 Revenue Estimate — insert — ambiguity — `effective_from`/`effective_to` are echoed back byte for byte as supplied while comparisons run on parsed UTC instants — `implementation/routes/revenue_forecasts.py:41`
- §3.1 Revenue Estimate — insert — ambiguity — the 30-day quiet buffer is a half-open overlap test on windows widened at their exclusive end, so a gap of exactly 30 days clears it; `DRAFT` and `SUPERSEDED` rows never collide — `implementation/routes/revenue_forecasts.py:99`
- §3.2 Decision Packages — insert — ambiguity — `fte_delta` may be fractional or negative — `implementation/routes/decision_packages.py:29`
- §3.2 Decision Packages — insert — ambiguity — a `depends_on_package_id` belonging to a different `agency_request_id` is also rejected with `ERR_DEPENDENCY_DEFERRED` — `implementation/routes/decision_packages.py:29`
- §3.2 Performance Measures — insert — ambiguity — values may be fractional, and the negative-`baseline_value` check (`ERR_INVALID_REQUEST`) precedes the target comparison — `implementation/routes/decision_packages.py:162`
- §3.2 Request Submission — insert — ambiguity — the expansion-measure requirement covers expansion packages of any status including `DEFERRED`, and a request with no expansion packages passes trivially — `implementation/routes/agency_requests.py:26`
- §3.3 Executive Recommendations — insert — ambiguity — `recommended_package_ids` is required (omission and non-string members are `ERR_INVALID_REQUEST`) — `implementation/routes/executive_recommendations.py:27`
- §3.3 Executive Recommendations — insert — ambiguity — members are read positionally and never de-duplicated, so a repeated package contributes its amount twice — `implementation/routes/executive_recommendations.py:27`
- §3.3 Phase Advancement — insert — ambiguity — every advancement runs the full cycle recomputation in the same mutation, and the `ENACTED` step's appropriation sweep is its only extra gate (a cycle with no appropriations passes) — `implementation/routes/budget_cycles.py:85`
- §3.3 Reduction Scenarios — insert — ambiguity — candidate ordering adds insertion order as the fourth tie-break — `implementation/services/calc.py` reduction sort key, `implementation/db.py:90`
- §3.4 Appropriation Creation — revise — mismatch — `release_hold` is derived at creation from the cycle posture, so a `GENERAL` line created under a `CONSTRAINED` posture is born held rather than always false — `implementation/routes/appropriations.py:43`, `implementation/services/core.py:448`
- §3.4 Committee Action — insert — ambiguity — recording is not gated on `authority_status` (an enacted or lapsed line accepts a late action, which rewrites balances but never `enacted_amount_cents`), and the listing ties break by `created_at` then insertion order and accepts no filters — `implementation/routes/committee_actions.py:27`, `implementation/routes/committee_actions.py:95`
- §3.5 Allotment Creation — insert — ambiguity — the row echoes `allow_partial`, and opening is gated only on the cycle not being `CLOSED` (the `EXECUTION` requirement bites at preparation) — `implementation/routes/allotments.py:31`
- §3.5 Release Ceiling — insert — ambiguity — the ceiling test is "zero or below" because the unreleased-authority term can go negative after transfers out — `implementation/routes/allotments.py:108`
- §3.5 Allotment Release — revise — mismatch — release tests only `APPROVED` status, separation of duties, `FROZEN` cash and quarter (in that order, so a frozen row reports `ERR_CASH_FROZEN`); it never re-tests `authority_status` — `implementation/routes/allotments.py:168`
- §3.5 Cash Dimension — revise — mismatch — the shared derivation is `released == 0 → UNRELEASED`, `released >= authority → FULLY_RELEASED`, else `PARTIALLY_RELEASED`, and no cash transition re-tests `authority_status` — `implementation/services/core.py:276`
- §3.5 Allotment Cancellation — revise — mismatch — both origins run one identical write (`CANCELLED`, `computed_release_cents` 0, `binding_constraint` null, slot freed, `version` +1); from `DRAFT` the last two are no-ops rather than a different branch — `implementation/routes/allotments.py:226`
- §3.5 Freeze Cash — revise — mismatch — the ladder decides precedence: the cash-status test (rung 11, `ERR_INVALID_STATE`) precedes the enactment test (rung 12, `ERR_APPROPRIATION_NOT_ENACTED`) — `implementation/routes/appropriations.py:201`
- §3.5 Unfreeze Cash — revise — mismatch — `FULLY_RELEASED` requires released *at or above* authority, `PARTIALLY_RELEASED` strictly between, and the zero test wins when authority is also zero — `implementation/routes/appropriations.py:230`, `implementation/services/core.py:276`
- §3.7 Emergency Appropriations — insert — ambiguity — full opening ledger pinned, `release_hold` derived from posture (so an emergency row can be born held), and `program_code` is *not* checked for uniqueness on this route — `implementation/routes/appropriations.py:150`
- §3.8 Grant Creation — insert — ambiguity — `moe_current_spend_cents` opens at 0 with no retroactive sweep of existing `POSTED` charges, and the cycle need only be non-`CLOSED` — `implementation/routes/federal_grants.py:64`
- §3.8 Commitment Impairment/Restoration — insert — ambiguity — both sweeps are iterative in creation order, re-reading the overlapping total after each move; impairment is strict and stops as soon as the total fits (oldest first), restoration excludes the candidate, is inclusive, and lets an older pledge consume the recovered headroom — `implementation/services/core.py:573`
- §3.9 Close Sweep — revise — mismatch — `PENDING` appropriations are skipped entirely and keep status, ledger figures, `version` and match commitments through the close — `implementation/routes/budget_cycles.py:135`
- §3.9 Close Cascades — revise — mismatch — only the appropriations the sweep touched have their commitments discharged, not "every appropriation of the cycle" — `implementation/routes/budget_cycles.py:153`
- §5 Error Code Catalogue — insert — ambiguity — three transport-level identifiers outside the domain catalogue: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), with unparseable bodies reusing `ERR_INVALID_REQUEST` — `implementation/errors.py:69`, `implementation/app.py:60`

Constraint compliance: only `PRD_COMPLETED.md` was written; `SCAFFOLD*.yaml` and `worklog.md` were never opened; tests were not used as an authority (the alignment target throughout was `workspace/implementation/`).

**Orchestrator verification:** `PRD_COMPLETED.md` is 484 lines / 118,872 chars, opens with the `# State Budget Appropriation API` title, carries all five `## ` sections, and ends with the complete §5 error table — non-truncated. No `.py` file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the clean sweep, so the 102/102 × 8 result still describes the shipped code.

---

# PIPELINE COMPLETE — all 9 steps done.

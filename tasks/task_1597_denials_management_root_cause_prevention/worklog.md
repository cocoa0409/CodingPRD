# Worklog — task_1597_denials_management_root_cause_prevention

## Step 1: Create Task Directory — 2026-08-14T00:21:22.000Z

Task directory `tasks/task_1597_denials_management_root_cause_prevention/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation args; no index scan performed, no other task_* directory touched. Difficulty target: beyond expert level ("Generate task hard than expert level!").

## Step 3: Copy Shared Files — 2026-08-14T00:21:35.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1597_denials_management_root_cause_prevention/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T01:29:07.000Z

The scaffold is complete and lint-clean. Final summary:

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1597_denials_management_root_cause_prevention/SCAFFOLD.yaml` (96.5 KB) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1597_denials_management_root_cause_prevention/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (84 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1597_denials_management_root_cause_prevention/SCAFFOLD_CORNER_DESIGN.yaml` (145 KB) — single top-level key `scaffold_corner_design`

### Counts

| Element | Count |
|---|---|
| Entities | 11 (Payer, PayerAppealPolicy, RemittanceCode, DenialCase, Appeal, AppealAttachment, RootCauseTask, WriteOffRequest, DepartmentScorecard, PreventionProgram, DenialEvent) |
| State machines | 8 (48 transitions; cycles on Appeal revise, RootCauseTask reopen, WriteOffRequest revise/rescind, DenialCase loops) |
| Calculations | 9 (incl. 2 pinned compensating invariants) |
| Validation priority rows | 11 |
| Endpoints | 57 (flat `/rcm/*` collections + `POST /rcm/_clock/set_current_utc`) |
| Error codes | 33 (all referenced outside the catalog — verified mechanically) |
| Roles | 5 (all `identity: opaque`) |
| OCC concurrency rules | 2 (both on `DenialCase.version`: assign + intake-correction, passing §1.2.1's serial-observability filter) |
| §1.8 instances | **21** (every rule ≥2; combinatorial_formula, priority_pair_validation_conflict, boundary_precision_check carry 3 each, covering modes (a)/(b)/(c) and three distinct error-category pairs) |
| §1.9 instances | **60** (56 active across all nine guide sections + 4 `excluded_because` stubs citing §1.8 instances) |
| Lint | **VERDICT: clean lint** — 687 calls scanned, zero violations; zero unbound `${var}`; all FK reverse-reachability GETs present; all formula-derived asserts pre-computed via Python (e.g., priority 49.00→54.00, pooled totals 66.67 vs 75.00, incidence 85.00 vs financial 92.50, tier projections 750000/1500000) |

### Notable design decisions

- **Flat topology + opaque roles + segregation_of_duties** (write-off requester ≠ approver, fix implementer ≠ verifier) — the diversity-prioritized combination; SoD is identity-string comparison, no Staff entity needed.
- **Logical clock with mandatory default 2026-08-01T00:00:00Z**; the expiry sweep deliberately skips denials with an in-flight (DRAFT/LETTER_GENERATED/SUBMITTED) appeal — this is what keeps the timely-filing submit gate reachable and enables the temporal-vs-constraint priority-conflict instance (without it, every past-deadline denial would be swept to CLOSED_EXPIRED before any submit attempt).
- **Cascade design**: depth-3 chain from the clock sweep (expiry → auto WriteOffRequest → scorecard counters) and depth-2 chain from outcome recording (denial dollars → scorecard/payer rate), satisfying Rule 4 from distinct triggers.
- **Policy-gap vs max-level exhaustion split**: missing next-level policy → `ERR_APPEAL_LEVEL_EXHAUSTED` with the denial staying IN_APPEAL; UPHELD at level 3 → CLOSED_EXHAUSTED — keeping both paths reachable.
- **Interval semantics contrast for Rule 8**: half-open `[from, to)` policy windows (adjacency legal) vs closed `[start, end]` program windows (touching conflicts), on different resources.
- **Endpoint count (57) intentionally exceeds the Expert guideline band (20–32)**: every endpoint is load-bearing via enum-value closure (each status value has a producing transition) and FK reverse-reachability; the guidelines explicitly permit this ("guidelines, not hard rules") and the user asked for maximum credible difficulty.

## Step 4: Generate PRD — 2026-08-14T01:51:43.000Z

All contracts pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1597_denials_management_root_cause_prevention/workspace/PRD.md` — 367 lines.

**Section list:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure [verbatim canonical block, byte-identical], 2.3 Pagination, 2.4 Logical Clock & Date Semantics, 2.5 Common Resource Properties, 2.6 Monetary Values/Rates/Rounding, 2.7 OCC on Denial Writes, 2.8 Validation Order & Error Precedence, 2.9 Conserved Dollar & Fix-Count Invariants, 2.10 Work-Queue Prioritization & Ranking, 2.11 Append-Only Denial Event Trail); §3 Business Logic (3.1 Payer/Policy/Code Administration, 3.2 Intake & Triage, 3.3 Assignment/Correction/Recovery Projection, 3.4 Multi-Level Appeal Pipeline, 3.5 Expiry & Clock Sweep, 3.6 Write-Off Approval Hierarchy, 3.7 Root-Cause Tasks & Recurrence Monitoring, 3.8 Scorecards/Programs/Analytics); §4 Endpoint Definitions (all 57 paths, 4-column table); §5 Error Code Catalogue (all 33 errors, 2-column table).

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): 91/91 entity fields, 65/65 endpoint input + computed-output identifiers (including `to_iso8601`, `current_utc`, `expired_denial_ids`, `variant`, `expected_recovery_cents`, `rate_applied`, `remaining_levels`, `group_by`, `rows`, `totals`), all query/filter params, 33/33 error IDs, 5/5 roles, all enum/state/event-type values — 0 missing. PASS.
- Contract 2 (Rule Coverage): 11/11 validation priorities expressed as an ordered first-match-wins gate list with the fiscal sub-order pinned; 2/2 OCC rules (assign + intake correction; `expected_denial_case_version` + `ERR_STALE_VERSION`/412, no time-overlap framing); 48/48 state transitions across 8 machines with preconditions paired to error IDs and all side-effect cascades (outcome 3-hop, sweep 3-hop, triage fan-out, verify/reopen scorecard counter sets); 9/9 calculations in reconstruction-test prose; 57/57 endpoint side effects and applies_to scopes; sibling branches (3 outcome kinds, 3 reversal from-states, 4 rescind restoration targets, revise/approve/reject/acknowledge pairs, 2 expiry from-states, 2 payer toggles) at equal density. PASS.
- Contract 3 (§3 Path Purity): 615 backtick tokens scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS. Also clean of operator pseudocode and fuzzy/approximating words.

**Coverage decisions / ambiguities resolved:**
1. `ERR_INVALID_RECURRENCE_LINK` "missing" vs priority-4 FK resolution — PRD assigns unresolvable `recurrence_of_task_id` to the 404 reference-resolution gate and resolved-but-invalid links (self-referential, non-`VERIFIED`, cross-department) to 422.
2. `RESOLVED_PAID` qualification — used the DenialCase machine's more specific condition (open balance reaches zero AND nothing written off); the written-off-greater-than-zero corner is left undefined, matching scaffold silence.
3. Level-1 appeal without a policy — reconciled `ERR_APPEAL_LEVEL_EXHAUSTED` against the `default_timely_filing_days` fallback: level 1 falls back to the payer default (first appeal always openable), exhaustion gate applies to levels beyond the first and to a next level past 3.
4. Reversal of a `CLOSED_EXHAUSTED` denial with no next-level policy — stated as leaving the denial in `CLOSED_EXHAUSTED` (minimal no-side-effect reading).
5. Constants kept in raw scaffold units (cents, days) for verbatim-pin precision rather than riskier unit conversions.
6. The forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T02:25:11.000Z

Generation complete and fully audited. Summary below.

### Test files (97 tests total, all collect cleanly under pytest)

| File | Tests | Covers |
|---|---|---|
| `test_01_intake_and_catalog.py` | 10 | payer defaults, intake-derived fields, pagination, missing payer_id, duplicate claim_number, deadline fallback, inactive-payer intake (×2), manager RBAC |
| `test_02_not_found_and_auth.py` | 5 | 401 gates, auth-beats-existence ordering, 404 variants, auditor read access |
| `test_03_queue_assignment_occ.py` | 4 | OCC stale/fresh assign, stale correction, correction re-derivation |
| `test_04_queue_priority.py` | 5 | multifactor score (×2), bucket boundary 50.00, terminal-denial zeroing, deterministic ranking |
| `test_05_recovery_projection.py` | 3 | gross vs net (×2), default-variant after level 1 |
| `test_06_appeal_pipeline.py` | 9 | letter revise cycle (×2), draft-submit rejection, response_due_date, next-level deadline, level chain/self-FK, already-active, non-appealable, withdraw-to-queue |
| `test_07_appeal_submission_gates.py` | 8 | deadline-date boundary (×2), expired-with-attachments, temporal-beats-constraint (×2), void semantics ×3 |
| `test_08_outcomes_and_reversals.py` | 11 | overturn cascade (×2), dollar-conservation reversal pair (×2), outcome shape, pre-submit, RESOLVED_PAID lockdown, auditor RBAC, workable-denial approve gate (×2), payer review-flag threshold |
| `test_09_writeoff_hierarchy.py` | 15 | tier evaluation order (×2), 2500000/2500001 boundary (×2), state-beats-fiscal (×2), SoD-beats-fiscal (×2), ceiling-before-balance, open-balance, duplicate pending, revise re-tier, rescind restore, immediate consistency, specialist RBAC |
| `test_10_clock_sweep.py` | 2 | expiry cascade hops 1–2 and hop 3 + queue eviction |
| `test_11_root_cause_tasks.py` | 8 | reopen cycle (×2), fix-count conservation (×2), monitoring-window close gate, verify SoD, recurrence-link validation, upstream-owner RBAC |
| `test_12_scorecards_and_programs.py` | 7 | incidence vs financial variants (×2), finalize lockdown, duplicate period, program touch-conflict (×2), program lifecycle |
| `test_13_policy_windows.py` | 2 | half-open adjacency allowed / overlap rejected |
| `test_14_analytics.py` | 5 | pooled totals rounding (×2), zero-denominator null rows (×2), date-window filter |
| `test_15_events_and_rbac.py` | 3 | INTAKE/TRIAGED audit events, specialist clock RBAC, re-triage rejection |

### Coverage vs design indices
- **Queue A (difficulty): 21/21 instances, 42 tests** (exactly 2 per instance, tag audit confirms zero shortfalls).
- **Queue B (corner): 55 of 56 non-stub instances** covered; all 4 `excluded_because:` stubs verified to resolve to real §1.8 instances and not translated.
- **Skipped: 1 instance** — `Corner/validations/appeal_level_exhausted_without_policy`. Reason: PRD-contradiction (not mere silence). The instance asserts the denial stays `IN_APPEAL` with null deadline after a level-1 UPHELD with no level-2 policy, and that re-appeal yields `ERR_APPEAL_LEVEL_EXHAUSTED`. PRD §3.4 uniquely derives the opposite: "otherwise `CLOSED_EXHAUSTED` with a null deadline", after which appeal creation hits the state gate (`ERR_DENIAL_INVALID_STATE`, gate 6 < gate 10). Emitting it would test against the PRD.

### PRD-first adjudications applied (weakened only where PRD underdetermines; no test skipped for these)
- Exact datetime-string equality (`submitted_at == "2026-08-05T00:00:00Z"`) relaxed to a date-prefix check — PRD pins the logical date, not the fractional-digit serialization.
- Literal `version == 1/3` assertions replaced with captured-version deltas or int/`!= supplied` checks — PRD says version "increments by one with every modification" but never pins the initial value.
- Event-list positional ordering dropped (both INTAKE and TRIAGED share the frozen logical clock's `created_at`; PRD's "creation timestamp ascending" doesn't break ties) — count/type/actor assertions retained.
- Totals-row `overturn_rate_pct == null` at zero pooled sample not asserted (PRD's "never zero and never an error" covers group rows only); the second zero-denominator test instead exercises the same covered rule on the `category` axis.

### Helper inventory (`test_helpers/`)
- `types.py` — 21 enums + 11 TypedDicts (DenialEvent correctly omits `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 57 endpoint methods (one per PRD §4 row)
- `api_errors.py` — 33 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — 11 per-entity asserters + `assert_denial_dollar_conservation` (§2.9)
- `factories.py` — 20 payload factories (input fields only)
- `constants.py` — all PRD thresholds (2500000 limit, 10000000 ceiling, 0.30 floor/3 sample, 90-day monitoring, 5000-cent appeal cost, bucket/tier boundaries, etc.)
- `test_users.py` — `TEST_USERS` for the 5 opaque roles + per-user-id builders for SoD scenarios
- `fixtures.py` — composite setups: `setup_catalog`, `make_queued_denial`, `make_lettered_appeal`, `make_submitted_appeal`, `setup_denial_with_submitted_appeal`, `make_verified_task`, `make_write_off`, `make_scorecard`, plus entity getters; all built on `get_success_data`

### Audit results
- `py_compile` clean; `pytest --collect-only` collects exactly 97 tests.
- Tag audit: 76/77 expected tags present (only the deliberately skipped instance absent), 0 extra tags, 0 difficulty shortfalls.
- Citation audit: all 97 docstrings carry a PRD citation with an 8-word verbatim substring grep-matching `workspace/PRD.md`; every docstring ends with exactly one `Design:` line.
- Zero `skip`/`skipif`/`xfail` markers; zero "scaffold" references in generated code.

## Step 6: Generate Implementation — 2026-08-14T02:28:36.000Z

Implementation complete and verified. Summary:

### File list (`tasks/task_1597_denials_management_root_cause_prevention/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Executable launcher; guarded `pip install` (no-op when Flask present), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 70 | Entry point; blueprints; error handlers (ApiError, 404/405/400/500); binds `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 40 | In-memory store (11 dicts keyed by id) + logical clock defaulting to 2026-08-01T00:00:00Z |
| `errors.py` | 47 | `ApiError` + all 33 error-id constants |
| `envelope.py` | 66 | Response envelope (`meta`/`response_type`/`data`), error body, `limit`/`offset` pagination (default 10, 1–100, `total_count`/`has_more`) |
| `auth.py` | 39 | `X-User-ID`/`X-User-Role` auth (401) + role gating (403) |
| `util.py` | 226 | Domain vocabularies, logical-clock helpers, ISO date/datetime parsing, schema validators (all → ERR_VALIDATION 400) |
| `services.py` | 459 | Record factory, reference resolution, deadline schedule, priority score, rate ladder (Fraction-exact), write-off economics, scorecard matching, letter template |
| `cascades.py` | 494 | Outcome record/reverse cascades, withdrawal, write-off approve/rescind restores, clock expiry sweep (created_at ASC), triage recurrence sweep, scorecard finalization (both score variants + tier) |
| `routes_admin.py` | 358 | Clock, payers (incl. PATCH toggle), policies (half-open overlap), remittance codes, programs (closed-window touching-conflict) |
| `routes_denials.py` | 335 | Intake, list/get, OCC-guarded PATCH + assign, triage (scorecard counters + auto task + recurrence sweep), recovery projection, ranked work queue |
| `routes_appeals.py` | 430 | Appeal create (level gating), letter/revise/submit (timely-filing + attachment gates), record/reverse-outcome, withdraw, attachments + void |
| `routes_tasks.py` | 210 | Task CRUD + acknowledge/implement-fix/verify (SoD)/close (monitoring window) |
| `routes_writeoffs.py` | 221 | Create/approve/reject/revise/rescind with pinned gate order (pending → denial state → SoD → balance → tier; ceiling before balance) |
| `routes_scorecards.py` | 237 | Scorecard create/finalize, overturn analytics (group payer/category, null-rate zero-resolved groups, totals rounded once from raw counts), denial events |

Total: 3,243 lines across 16 files.

### Endpoint coverage
57/57 endpoints from the scaffold table (1 clock, 4 payers, 3 policies, 2 remittance-codes, 8 denial-cases incl. work-queue and recovery-projection, 9 appeals, 4 attachments, 7 tasks, 7 write-offs, 4 scorecards, 5 programs, 1 analytics, 2 events).

### Key spec fidelity points
- In-memory only; empty store at boot; no seeding/persistence (grep-verified)
- Logical clock default 2026-08-01T00:00:00Z; all timestamps from it; date-granular deadline comparisons
- OCC `expected_denial_case_version` → 412 on assign/PATCH; version bumps on every denial mutation including cascades and submit
- Exact gate precedence per PRD §2.8; approve order = pending → denial state → SoD → balance → tier authority
- Money conserved exactly (open = denied − recovered − written-off); rates/thresholds via `Fraction` (0.30 floor strict, sample ≥ 3); scores/pct via `Decimal` ROUND_HALF_UP, rounded once
- Sweep: QUEUED and unshielded IN_APPEAL expire in created_at ASC, auto write-off (`system`), scorecard counters, priority rescore

### Boot verification
`bash start.sh` with `PORT` booted cleanly from fresh processes repeatedly; unauthenticated request returns the exact error envelope, authenticated list returns the paginated envelope with the default clock in timestamps; process killed and port freed afterward. Four smoke suites (100+ assertions covering intake→triage→assign→appeal→outcome→reversal→write-off→rescind, recurrence reopen, exhaustion, review flag, windows, analytics, pagination, all major error codes) pass with 0 failures, each run against its own fresh server boot to match per-test-server isolation.

### Diagnostic iteration (2026-08-14)
- Round 1 (8-round parallel sweep): 84/97 in every round; union = 13 tests failing deterministically with `TypeError: 'dict' object is not callable`.
- Root cause (test artifact bug, no PRD-coverage impact): 13 test functions in test_08/test_09/test_11 declared fixture parameters (`manager_headers`, `specialist_headers`, `director_headers`) that shadowed the same-named per-user header-builder functions imported from `test_helpers`; calling `manager_headers("mgr-1")` then hit the injected fixture dict.
- Fix: removed the shadowing fixture parameters from the 13 test signatures and converted the few remaining bare-dict usages of those names into helper calls (e.g. `manager_headers("mgr-1")`). No assertions weakened, no tests deleted, no implementation changes.
- Round 2 (8-round parallel sweep): 97/97 in all 8 rounds; failure union empty.

## Step 7: Run Tests and Iterate — 2026-08-14T02:46:31.000Z

Clean exit — all 8 parallel rounds pass 97/97.

**Iterations run:** 2 (round 1: 84/97 in all 8 rounds → fix → round 2: 97/97 in all 8 rounds, failure union empty).

**Tests deleted:** None. Every failing test's assertion traced to verbatim PRD prose (§3.6 write-off approval hierarchy, §2.8 gate precedence, §3.7 task-verification SoD); coverage and unique derivability held for all 13.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`** — single root cause across all 13 failures: test functions declared fixture parameters (`manager_headers`, `specialist_headers`, `director_headers`) that shadowed the same-named per-user header-builder functions imported from `test_helpers`; the injected fixture dict then made calls like `manager_headers("mgr-1")` raise `TypeError: 'dict' object is not callable`. Fixes:
- `test_suite/test_08_outcomes_and_reversals.py` — removed shadowing param from `test_writeoff_approve_against_resolved_paid_rejected` and `test_writeoff_approve_blocked_request_undecided`; converted one bare `manager_headers` dict usage to `manager_headers("mgr-1")`.
- `test_suite/test_09_writeoff_hierarchy.py` — removed shadowing params from `test_manager_approval_limit_exact_boundary_standard`, `test_manager_approval_limit_one_cent_over_escalated`, `test_writeoff_approve_state_beats_fiscal`, `test_writeoff_approve_state_failure_leaves_request_rejected`, `test_writeoff_approve_sod_beats_fiscal`, `test_writeoff_self_approve_leaves_request_pending`, `test_writeoff_pending_then_duplicate_rejected`, `test_writeoff_revise_cycle_retiers`, `test_immediate_visibility_after_writeoff_approve`, `test_specialist_cannot_approve_writeoff`; converted 5 residual bare-name dict usages (post-approval/duplicate GET-by-id reads) into helper calls.
- `test_suite/test_11_root_cause_tasks.py` — removed shadowing `manager_headers` param from `test_task_verify_by_implementer_rejected`.

A full-suite scan confirmed no remaining signature/body collisions (all other param declarations use the fixture as a dict only, which is the intended form).

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; all failures were test-artifact bugs.

## Step 8: Finalize PRD — 2026-08-14T02:52:57.000Z

Done. `workspace/PRD_FINALIZED.md` produced and is **byte-identical to PRD.md** — no edits were warranted.

**Verdict on the step_7_diff:** it contains only pure test-artifact bugs with no PRD silence or mismatch. All 13 round-1 failures trace to one Python name-shadowing defect: `test_suite/conftest.py:18-29` defines pytest fixtures named `specialist_headers` / `manager_headers` / `director_headers` that return dicts, while `test_helpers/test_users.py:20-32` defines same-named header-builder **functions**. Tests that imported the helpers and also declared the fixture parameter had the imported function shadowed by the injected dict, so calls like `manager_headers("mgr-1")` raised `TypeError: 'dict' object is not callable`. Step 7's fixes (removing the shadowing params, converting residual bare-name dict usages to helper calls) changed no assertion semantics, deleted no tests, and touched neither `test_helpers/` nor `implementation/`.

**Due-diligence verification (per diff item, behaviors confirmed already pinned in PRD and matched by impl):**
- test_08 `test_writeoff_approve_against_resolved_paid_rejected` — PRD §3.6 (line 235) pins approvable denial states and `ERR_DENIAL_INVALID_STATE`; impl `routes_writeoffs.py:117-122` matches.
- test_08 `test_writeoff_approve_blocked_request_undecided` — PRD line 235 pins `ERR_WRITE_OFF_NOT_PENDING`; impl `routes_writeoffs.py:112-115` matches.
- test_09 limit-boundary pair — PRD line 233 pins "2500000 cents or less" → STANDARD, ESCALATED otherwise; impl `services.py:25` (`MANAGER_APPROVAL_LIMIT_CENTS = 2500000`) matches exactly, including the boundary direction.
- test_09 state-beats-fiscal / sod-beats-fiscal / approve-failure-leaves-rejected — PRD §2.8 validation pipeline (lines 132-137) and §3.6's "gated in a fixed order" pin precedence; impl approve chain (`routes_writeoffs.py:112-141`: request state → denial state → SoD → balance re-check → tier authority) matches.
- test_09 self-approve-pending, duplicate-rejected, revise-cycle, immediate-visibility, specialist-cannot-approve — pinned by PRD lines 135 (SoD), 231 (`ERR_WRITE_OFF_ALREADY_PENDING`, ceiling 10000000), 239 (revision), and the endpoint RBAC table line 312; impl `routes_writeoffs.py:78-83,123-128` and `services.py:26` match.
- test_11 `test_task_verify_by_implementer_rejected` — PRD line 249 pins verifier ≠ `implemented_by_user_id` → `ERR_SEGREGATION_OF_DUTIES`; impl `routes_tasks.py:158-164` matches.

**Line counts / delta:** PRD.md 367 lines, PRD_FINALIZED.md 367 lines, 0% delta (`cmp` confirms byte-identical).

**Changes:** none — zero inserts, zero revisions.

**Pre-edit search log:** no edits were committed, so no per-edit searches apply. The verification greps/reads above (conftest.py, test_users.py, the three fixed test files, `routes_writeoffs.py`, `routes_tasks.py`, `services.py`, and PRD §2.8/§3.6/§3.7) constitute the item-by-item check that each diff entry is a fixture artifact rather than a PRD silence.

## Step 9: Complete PRD — 2026-08-14T03:35:47.000Z

Done. PRD_COMPLETED.md is written and verified. Summary:

### Stats
- Source: `PRD_FINALIZED.md` — 367 lines / 63,818 chars. Output: `PRD_COMPLETED.md` — 368 lines / 67,658 chars. Delta: **+1 line, +3,840 chars**.
- **Ambiguity-pins: 28** · **Mismatch-revisions: 5** (28 diff hunks: 27 in-paragraph revisions + 1 inserted bullet; no new sections).

### Changes (one per bullet)

- §2.2 — insert — ambiguity — undefined paths yield `ERR_NOT_FOUND` (404); a defined path with an unsupported method carries the same `ERR_NOT_FOUND` body at HTTP 405 — `implementation/app.py:41-47`.
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset` rejected `ERR_VALIDATION` (400); offset minimum 0 — `implementation/envelope.py:34-53`.
- §2.3 — insert — ambiguity — identical `created_at` ties ordered by creation sequence; list filters match by exact equality and a non-matching filter value yields an empty list, not an error — `implementation/util.py:224-226`, list handlers in `routes_*.py`.
- §2.3 — insert — ambiguity — `total_count` is the full pre-pagination count; `has_more` true iff `offset + limit < total_count` — `implementation/envelope.py:56-66`.
- §2.4 — insert — ambiguity — clock accepts any ISO 8601 instant (offsetless read as UTC) with no monotonicity check; backward sets allowed — `implementation/routes_admin.py:54-62`, `implementation/util.py:81-94`.
- §2.5 — insert — ambiguity — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — `implementation/services.py:62-69`.
- §2.9 — revise — mismatch — fix-count invariant restated as event-sourced: verification lands on the OPEN scorecard covering the verification date, reopen subtraction on the one covering the reopen date; the net-zero pair holds only when both fall in the same period (impl breaks the old "currently VERIFIED in period" identity on cross-period reopens) — `implementation/cascades.py:414-423`, `implementation/routes_tasks.py:175-184`.
- §3.1 — insert — ambiguity — a payer PATCH that changes no stored value leaves `version` unchanged — `implementation/routes_admin.py:120-135`.
- §3.1 — insert — ambiguity — `response_window_days` must be positive when supplied — `implementation/routes_admin.py:156-157`.
- §3.1 — insert — ambiguity — supplied `effective_to` must be later than `effective_from`, else `ERR_VALIDATION` (400) — `implementation/routes_admin.py:163-166`.
- §3.1 — insert — ambiguity — duplicate remittance-code string rejected with `ERR_VALIDATION` (400) — `implementation/routes_admin.py:234-238`.
- §3.1 — revise — mismatch — "all three catalogs are listable and retrievable" → payers and policies retrievable by id; remittance codes expose no get-by-id endpoint — `implementation/routes_admin.py:221-267` (no such route).
- §3.2 — insert — ambiguity — auto-created task's `description` is `Auto-created PROCESS_FIX task for preventable denial <claim_number>`; the `TASK_AUTO_CREATED` event's actor is the triaging specialist, not `system` — `implementation/cascades.py:361-362,377-384`.
- §3.3 — insert — ambiguity — intake correction: supplied amounts must be positive and the merged denied ≤ billed check (`ERR_VALIDATION`) runs after the state precondition — `implementation/routes_denials.py:199-204`.
- §3.3 — insert — ambiguity — invalid `variant` query value rejected `ERR_VALIDATION` (400) — `implementation/routes_denials.py:157-159`.
- §3.3 — revise — ambiguity — net variant starts from the rounded gross figure, not the unrounded product — `implementation/services.py:330-333`.
- §3.3 — revise — mismatch — projection available for a denial in **any** status, terminal or not (impl has no state gate) — `implementation/routes_denials.py:154-161`.
- §3.3 — insert — ambiguity — `rate_applied` reports the exact rate unrounded — `implementation/services.py:335-339`.
- §3.4 — insert — ambiguity — appeal-creation level-existence gate anchored at the current logical date — `implementation/routes_appeals.py:101-106`.
- §3.4 — insert — ambiguity — `previous_appeal_id` is the most recently created non-`WITHDRAWN` appeal one level lower — `implementation/routes_appeals.py:107-118`.
- §3.4 — insert — ambiguity — exact letter template: newline-joined `APPEAL LETTER` / `claim_number=` / `category=` / `level_number=` / `denied_amount_cents=` / `attachments=` lines; manifest is one comma-joined sorted entry per ACTIVE attachment — `implementation/services.py:445-459`.
- §3.4 — insert — ambiguity — submission: a null `next_appeal_deadline` fails the timeliness gate; when no effective policy covers the level, requirements are empty and `response_due_date` uses the 30-day default — `implementation/routes_appeals.py:244-267`.
- §3.4 — insert — ambiguity — an `OVERTURNED` outcome with prior write-offs resolves to `RESOLVED_WRITTEN_OFF` (PRD only pinned the nothing-written-off branch) — `implementation/cascades.py:62-67`.
- §3.4 — insert — ambiguity — reversing an outcome while the denial is `RESOLVED_WRITTEN_OFF` keeps status and null deadline, applying only the dollar correction — `implementation/cascades.py:119-139`.
- §3.5 — insert — ambiguity — denials in `RECEIVED` or `TRIAGED` are never expiry candidates — `implementation/cascades.py:327-341`.
- §3.5 — revise — mismatch — hop two auto-creates the write-off only when the expired denial has a positive open balance and no pending request; hop three increments `auto_writeoff_request_count` only when a request was actually created — `implementation/cascades.py:301-319`.
- §3.6 — revise — mismatch — deleted the note that `decided_by_user_id` may hold `system`; impl never records a system-generated decision — `implementation/cascades.py:234-240`.
- §3.6 — insert — ambiguity — revision requires a positive amount and retains the rejection's decision fields (`decision_reason`, `decided_by_user_id`, `decided_at`) until the next decision — `implementation/routes_writeoffs.py:175-197`.
- §3.6 — insert — ambiguity — rescission re-stamps `decided_by_user_id` and `decided_at` to the rescinding director and the logical timestamp — `implementation/cascades.py:236-240`.
- §3.6 — insert — ambiguity — rescission deadline rebuild: `QUEUED` recomputed from the current level-1 schedule over the remittance date; `IN_APPEAL` anchored at the latest outcome date among outcome-state appeals, falling back to the level-1 schedule when no outcome exists, clearing to null when the next level exceeds 3 or has no covering policy — `implementation/cascades.py:247-266`.
- §3.7 — insert — ambiguity — recurrence-reopen scorecard adjustments land on the OPEN scorecard covering the triage date — `implementation/cascades.py:414`.
- §3.8 — insert — ambiguity — when multiple OPEN scorecards of a department cover an event date, the earliest-created absorbs the event — `implementation/services.py:414-431`.
- §3.8 — insert — ambiguity — `target_reduction_pct` may be any JSON number in range — `implementation/routes_admin.py:283`.
- §3.8 — insert — ambiguity — analytics: rows keyed by `payer_id`/`category`, ordered by key ascending, paginated with standard meta; totals carry pooled counts and a pooled percentage that is null when pooled resolved is zero; missing/invalid `group_by` or malformed date bounds are `ERR_VALIDATION` (400) — `implementation/routes_scorecards.py:126-213`.

All edits are inline inserts/revisions within existing paragraphs; no sections added, no behavior invented beyond what `implementation/` exhibits.

## Pipeline complete — all 9 steps done. Final sweep: 97/97 tests passing in all 8 parallel rounds (per-test-server isolation).

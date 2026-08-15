# Worklog — task_1823_regulated_role_training_compliance

## Step 1: Create Task Directory — 2026-08-14T19:01:00.000Z

Task directory `tasks/task_1823_regulated_role_training_compliance/` and `workspace/` were created by the pipeline launcher before this orchestrator run (Step 1 pre-completed per command args). No new index computed; no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-14T19:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1823_regulated_role_training_compliance/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T19:52:40.000Z

Scaffold generation complete for task 1823. All three artifacts written and lint-clean.

### Output files (all written, YAML-valid)

- `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/SCAFFOLD.yaml` — §1.0–§1.7 only (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` key present; response envelope emitted verbatim; scenario stored verbatim)
- `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

### Counts

**SCAFFOLD.yaml**: 15 entities, 12 state machines (incl. parallel progress×deadline dimensions on TrainingAssignment, cyclic Attestation denial loop, branching EmployeeRoleChange with scheduled apply/reverse), 9 calculations, 11 ordered validation priority rows, 63 endpoints, 42 error codes, 6 roles (ComplianceAdmin/HRAdmin/Auditor opaque; Manager/Employee entity_backed:Employee; Anonymous), 4 OCC concurrency rules, archetype compliance_audit + workflow_orchestration.

**§1.8 difficulty design**: 18 instances (exactly 2 per rule × 9 rules), all with structured `setup_api_calls`/`trigger`/`assert`. Highlights: CALENDAR vs BUSINESS_DAYS due dates (2026-08-08 vs 2026-08-10 from identical inputs), STRICT 50.00 vs AUDIT_LENIENT 100.00 compliance rates, HARD/SOFT escalation acceleration (ceil(interval/2)), nested-rounding weighted pass rate pinned at 85.72 vs non-conformant 85.71, depth-3 cascades from two different triggers, state-vs-safety and temporal-vs-constraint priority pairs, inclusive score boundary vs strict overdue boundary, half-open version windows vs closed+buffered leave windows, due-timestamp and verified-count compensating invariants.

**§1.9 corner design**: 64 entries across all 9 taxonomy sections (60 active instances + 4 `excluded_because` stubs citing difficulty instances). Covers defaults, required/system fields, invalid transitions, terminal lockdowns, cascade sweeps, expiry/recurrence boundary (inclusive `>=` at expiry instant), termination cascade, notice dedupe, retention precedence override→regulator fallback, empty-population zero metrics, prospective passing-score changes, evidence-tier ordering, SoD self-action denial, ownership, OCC 412 twin cases (stale 412 vs fresh 409), deferred sweep application, envelope/pagination, and immediate consistency.

### Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (899 calls scanned, exit 0)
- Additional audits passed: 82 instance names unique across both design files; all `grounds:` resolve to declared §1.1–§1.7 elements; all 42 error codes referenced by validations/transitions; all stub `difficulty_instance` refs exist; no forbidden concurrency vocabulary; all formula-derived assert literals (dates, rates 85.72/66.67/88.33/50.00, escalation thresholds, retro/reverse windows, leave buffer arithmetic) were computed and verified by executing the formulas in Python.

Note: the task directory also contains a pre-existing `worklog.md` and `workspace/` (created before my run; untouched). No sibling task directories were inspected at any point.

## Step 4: Generate PRD — 2026-08-14T20:08:00.000Z

All checks pass. The PRD is complete and verified. Final summary:

### Generated Artifact

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/workspace/PRD.md` — 362 lines.

### PRD Section List

- **1. Introduction** (2 paragraphs: business context + determinism/segregation-of-duties design commitments)
- **2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (headers, 6 roles, per-role identity prose for `entity_backed` vs `opaque`)
  - 2.2 API Response Structure (emitted **byte-identical** to `section-2.2-response-structure.md`)
  - 2.3 Pagination and List Ordering (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields, domain-ordering exceptions)
  - 2.4 Common Resource Properties (`id` UUID no prefix, `created_at`/`updated_at` ISO 8601 UTC 3-fractional-digits, `version`)
  - 2.5 The Logical Clock and the Deterministic Sweep (default `2026-08-01T00:00:00Z`, pinned 5-step order, all 11 sweep counters)
  - 2.6 Precision, Rounding, and Calendar Arithmetic (2dp round-half-up, second precision UTC, month-clamping, 86,400-second days)
  - 2.7 Optimistic Concurrency Control (all 4 OCC rules: `expected_regulator_version` / `expected_curriculum_version` / `expected_assignment_version` ×2, `ERR_STALE_VERSION` 412)
  - 2.8 Nested Resource Retrieval and Identifier Existence (left-to-right, `ERR_NOT_FOUND`)
  - 2.9 Validation Order and Error Precedence (all 11 priority tiers in order + both priority-conflict pins)
- **3. Business Logic & Workflows** (7 subsections, entity-lifecycle grouping)
  - 3.1 Regulators, Curricula, and Versioned Content · 3.2 Roles, Requirements, and Assignment Seeding · 3.3 Employee Lifecycle (hire/leave/role-change/termination) · 3.4 Training Assignment workflow · 3.5 Due Dates, Extensions, Escalation Ladder · 3.6 Compliance Posture, Attestation Campaigns, Exceptions · 3.7 Audit Reporting and Effectiveness
- **4. Endpoint Definitions** (63-row table, 4 columns only)
- **5. Error Code Catalogue** (42-row table, 2 columns only; no trailing audit footer)

### Zero-Silence Rule Coverage (scaffold → PRD mapping)

- `scenario` → §1; `response_envelope` → §2.2 (verbatim) + §2.3
- `entities` (15 entities, 106 fields) → §2.4 + scattered §3.1–3.7 narrative — **106/106 field names present in backticks**
- `state_machines` (12 machines, 42 transitions) → §3.1–3.6; every precondition paired with its scaffold `error_id`, every side effect stated (incl. full cascades: terminate, role-change apply/reverse, campaign close, HARD-escalation block, completion void)
- `calculations` (9) → due-date computation & escalation thresholds in §3.5; posture block in §3.6; compliance rate, weighted first-attempt pass rate (pinned round-then-average order), retention expiry in §3.7; validity expiry in §3.4; campaign response rate in §3.6; effectiveness in §3.7 — all in operator-free prose with exact boundary semantics
- `validations` (11 priorities) → §2.9 ordered list + per-workflow error pairing in §3; both dual-failure pins expressed
- `concurrency_rules` (4) → §2.7, reinforced in §3.5
- `endpoints` (63) → §4 table; request-body identifiers (49/49) and query params (12/12) covered in §3/§2 prose
- `errors` (42) → §5 table; all 42 IDs also mentioned in §2/§3 prose
- `roles` (6) → §2.1 with exact spelling and identity-semantics prose per role

### Hard Contract Reports

- **Contract 1 (Field-Name Coverage):** entities 106/106, request_body 49/49, query_params 12/12, output identifiers 26/26, path param `{id}` present — **PASS** (4 initially missing FK names — `assignment_id` ×2, `attestation_id`, `kind` — were repaired and re-verified)
- **Contract 2 (Rule Coverage):** 11/11 validation priorities, 4/4 OCC rules, 42/42 transitions, 9/9 calculations, 42/42 error conditions matchable, all side-effect scopes expressed, sibling branches symmetric — **PASS** (one gap found and fixed: sweep step-4 `VERIFIED_COMPLETED → EXPIRED` transition with inclusive expiry boundary and `RECURRENCE` re-assignment conditions)
- **Contract 3 (§3 Path Purity):** 646 backtick tokens scanned, 0 path/method violations — **PASS**
- Also verified: §2.2 byte-identical, zero pseudocode operators in prose, all 61 enum/state strings present, all 6 role names exact.

The constraint files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, and no sibling task directories were read.

## Step 5: Generate Unit Tests — 2026-08-14T20:35:00.000Z

Generation complete. Final summary:

### Files generated

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/test_helpers/`
- `types.py` — 18 enums + 15 entity TypedDicts (all entities carry common fields in this domain)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~56)
- `api_errors.py` — all 42 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural asserts, `assert_due_at_invariant`, plus `assert_instant_equal` (timestamps compared as parsed instants — PRD pins the instant via the logical clock, not the serialization) and `assert_pct_equal`
- `factories.py`, `constants.py` (clock default, thresholds, standard instants), `test_users.py` (opaque-role constants + `make_manager/employee_headers` per-instance builders), `fixtures.py` (tiered composites: `setup_curriculum_stack`, `setup_employee_with_assignment`, `setup_managed_employee_with_assignment`, `setup_open_campaign_with_attestation`, submit/accept/reject/void, campaign/attestation helpers), `__init__.py` barrel

**`test_suite/` (13 files: conftest + 12 test files, 94 tests)** — same directory root, `test_01_api_basics.py` through `test_12_security_and_concurrency.py`, organized by concern (config/envelope, curricula/versions/requirements, due dates/clock, assignment workflow, extensions, deadline sweeps/expiry, posture/escalation, role changes, employee lifecycle, attestations/campaigns, audit reporting, security/OCC).

### Counts per queue
- **Queue A (Difficulty): 18/18 instances, 36 tests** (exactly 2 per instance), 0 skips
- **Queue B (Corner): 58/60 non-stub instances, 58 tests** (1 per instance), 2 skips; 4 `excluded_because:` stubs not translated — all 4 `difficulty_instance` cross-references verified resolving (`score_exactly_at_passing_boundary`, `curriculum_version_half_open_adjacency`, `leave_closed_interval_buffer_gap`, `sweep_overdue_requires_strictly_after_due`)

### Skip list (PRD-first filter)
1. **Corner/entities/curriculum_create_with_system_field_input_ignored** — PRD never states whether client-supplied system/computed fields in a create body are ignored or rejected; two faithful readers could ship 200-DRAFT vs 400-schema-rejection. Fails unique derivability.
2. **Corner/rbac/level3_escalation_notice_acknowledged_by_compliance_admin** — the instance asserts `ERR_OWNERSHIP_MISMATCH` for a Manager ack of a level-3 (recipient-null) notice, but PRD §3.5 states "for a level-3 notice with its null recipient, only a `ComplianceAdmin` may acknowledge — anyone else draws `ERR_FORBIDDEN_ROLE`" (§5 repeats it). Asserted outcome contradicted by PRD.

### Design-tag audit
94/94 tests carry exactly one `Design:` tag as the last docstring line; every tag resolves to a real instance in the source yamls (verified programmatically); no tag points at a stub; no untagged or dual-tagged tests.

### Quality gates
- Verbatim-citation pass: every test's PRD quote matched PRD.md via normalized 10-word-window grep (94/94)
- `python -m py_compile` clean; `pytest --collect-only` collects 94 tests; no `skip`/`skipif`/`xfail` markers; no "scaffold" mentions; pyflakes clean on `test_suite/`
- OCC tests assert version increments relative to the captured creation version (`v+1`), since PRD pins "increments … by 1" but not the initial value; the regulator-defaults test likewise keeps only the PRD-derivable sub-assertions (defaults 10/7, status ACTIVE)

## Step 6: Generate Implementation — 2026-08-14T20:35:00.000Z

Complete Python + Flask implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/workspace/implementation/`.

### File list
- `start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask app factory, envelope-wrapped error handlers (ApiError/404/405/500), global store lock per request, blueprint registration under `/compliance`
- `db.py` — empty-at-boot in-memory store (no seeding) + logical clock defaulting to `2026-08-01T00:00:00Z`
- `errors.py` — all 41 error IDs with exact HTTP statuses from the catalog
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1..100), typed field validators
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (P1 400, P2 403; Anonymous/unrecognized roles denied everywhere)
- `util.py` — ISO-8601 parse/format (3-fraction-digit `Z`), business-day counting, month/year arithmetic with day clamping, Decimal round-half-up helpers
- `services.py` — due-date computation (CALENDAR / BUSINESS_DAYS), deadline-stage thresholds with snapshotted regulator config (PRD non-retroactivity), posture block evaluation + attestation BLOCKED/PENDING cascades, role-change apply/reverse, termination cascade, campaign close/finalize, audit metrics, 5-step sweep
- `routes/admin.py`, `routes/people.py`, `routes/assignments.py`, `routes/attestations.py`, `routes/reports.py`, `routes/ops.py`

### Endpoints
63 endpoints — the full PRD §4 table (regulators, roles, requirements, curricula + versions + effectiveness, employees, leaves, role-changes, assignments + extensions + cancel, completions + accept/reject/void, escalation notices + acknowledge, campaigns + open/close/finalize, attestations + attest, exceptions + approve/deny, audit-reports, `_clock/set_current_utc`, `_sweeps/run`).

### State machines implemented (12)
TrainingAssignment (two parallel dimensions: progress × deadline, with strict OVERDUE/ESCALATED boundary pins and HARD half-interval acceleration), CompletionRecord, Attestation (cyclic PENDING↔EXCEPTION_PENDING, PENDING↔BLOCKED), AttestationCampaign (DRAFT→OPEN→CLOSED→FINALIZED), Curriculum, Regulator, Role, RoleRequirement, Employee (incl. leave freeze/unfreeze and full termination cascade), EmployeeRoleChange (SCHEDULED/APPLIED/CANCELLED/REVERSED with sweep-only application and 14-day reversal), AttestationException (incl. `AUTO_DENIED_AT_CLOSE`), EscalationNotice. OCC via `expected_regulator_version`/`expected_curriculum_version`/`expected_assignment_version` → `ERR_STALE_VERSION` 412, checked at priority 6.

### Verification
Four smoke rounds against a live server all passed after corrections (every failure traced to test-script arithmetic, not implementation): envelope shape, auth/RBAC/ownership/self-action ordering, OCC, due-date math (calendar + business days incl. weekend skip), DUE_SOON-at-birth, escalation with level-2 backfill + level-3, HARD-escalation compliance block ↔ attestation BLOCKED cascade and unblock paths, extension grant/revoke invariants (`due_at == base_due_at + active_extension_days`), leave normalization + 1-day buffer overlap + freeze/unfreeze, role-change cancel/recreate with curriculum-keyed coverage, reverse with REVERSAL seeding, month-end-clamped `expires_at` (Jan 31 + 1mo → Feb 28), inclusive expiry + RECURRENCE, max-attempts FAILED, manual remedial retake, campaign window pins (inclusive open, strict auto-close), exception deny-cycle/approve, pinned round-first weighted pass rate (33.34 where pooling yields 33.33), audit metrics + recordkeeping year arithmetic, pinned error precedences (P7>P11, P8>P9).

**Clean-boot note**: server was killed and relaunched via `bash start.sh` on port 19323; fresh process answered requests correctly with an empty store (`GET /compliance/employees` → `total_count: 0`), default logical clock (`2026-08-01T00:00:00.000Z` in meta), zero-counter sweep, and correct 400 auth-envelope behavior — no carry-over state between restarts.

## Step 7: Test–Fix Loop (8-round stability sweep) — 2026-08-14

Ran the full diagnostic loop against the existing implementation + test suite:
`prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30`, 8 parallel rounds.

- Round 1: 94/94 passed (0 failed, 0 skipped, 0 errors)
- Round 2: 94/94 passed
- Round 3: 94/94 passed
- Round 4: 94/94 passed
- Round 5: 94/94 passed
- Round 6: 94/94 passed
- Round 7: 94/94 passed
- Round 8: 94/94 passed

Union of failing tests across all 8 rounds: empty. No flakiness surfaced.
No test deletions, no test_helper fixes, no test_suite fixes, no implementation fixes were required.

## Step 7: Test-Iterate Loop — 2026-08-14T20:47:00.000Z

Orchestrator record (verbatim subagent summary; the subagent's own sweep-round entry appears above):

- **Iterations run:** 1 (one 8-round parallel stability sweep; exit condition met immediately)
- **Sweep result:** All 8 rounds passed 94/94 — `passed == total`, 0 failed, 0 skipped, 0 errors in every round. Union of failing tests across rounds: empty. No flakiness surfaced (no test passed in some rounds but failed in others).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance` was already in a converged state from the prior pipeline steps (documented in `worklog.md` Step 6): the Flask implementation under `workspace/implementation/` faithfully covers the PRD (63 endpoints, 12 state machines, pinned error-precedence ordering, OCC, sweep-driven transitions, round-half-up pinned weighted metrics), and the 94-test suite traces to verbatim PRD sentences. The 8-round sweep confirmed stability under `per-test-server` isolation with 8 concurrent port-allocated runs. I appended a Step 7 entry to the task's `worklog.md` recording the clean sweep.

## Step 8: Finalize PRD — 2026-08-14T20:47:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-14T20:52:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1823_regulated_role_training_compliance/workspace/PRD_COMPLETED.md`.

### Summary

**Source:** `workspace/PRD.md` (no PRD_FINALIZED.md existed). Both files are 361 lines — all changes are in-place paragraph/bullet revisions. Char delta: 64,464 → 67,144 (**+2,680 chars**, 16 lines touched).

**Counts:** 16 ambiguity-pins, 2 mismatch-revisions (18 logical changes across 16 edited lines).

**Changes:**

- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-integer values fail `ERR_INVALID_REQUEST`; list filters are exact-match, unrecognized values yield an empty page — `implementation/response.py:57-74`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `implementation/db.py:37-40`
- §2.5 — insert — ambiguity — clock-set adopts the supplied instant verbatim, may move the clock backward — `implementation/routes/ops.py:13-19`
- §3.1 (regulator create) — insert — ambiguity — duplicate `code` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/admin.py:73-75`
- §3.1 (deadline_mode) — insert — ambiguity — a PATCH body naming `deadline_mode` is rejected with `ERR_INVALID_REQUEST` — `implementation/routes/admin.py:98-99`
- §3.1 (regulator update/retire) — revise — ambiguity — version increments on any successful update even a no-op; field updates accepted at any status; only `ACTIVE`→`RETIRED` transition exists (others `ERR_INVALID_STATE`, same-status is a no-op) — `implementation/routes/admin.py:109-128`
- §3.1 (curriculum create) — revise — ambiguity — duplicate `code` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/admin.py:260-262`
- §3.1 (curriculum update coverage) — revise — **mismatch** — the update parenthetical omitted `passing_score_pct`, which the impl accepts; also pinned version increment on no-change updates — `implementation/routes/admin.py:306,338-348`
- §3.1 (curriculum status machine) — insert — ambiguity — only `DRAFT`→`ACTIVE`/`RETIRED` and `ACTIVE`→`RETIRED`; other transitions `ERR_INVALID_STATE`; same-status no-op; field updates accepted on `RETIRED` curricula — `implementation/routes/admin.py:321-325`
- §3.2 (role create) — revise — ambiguity — duplicate `code` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/admin.py:140-142`
- §3.2 (role retire) — revise — **mismatch** — PRD claimed a retired role is "excluded from requirement sweeps"; impl permits requirement creation on a retired role and seeds its incumbents normally — `implementation/routes/admin.py:177-209`
- §3.3 (employee create) — revise — ambiguity — duplicate `employee_no` rejected with `ERR_INVALID_REQUEST`; the named role's `status` is not consulted (registration into a `RETIRED` role succeeds) — `implementation/routes/people.py:55-62`
- §3.4 (voiding) — insert — ambiguity — void stamps `reviewed_by`/`review_note` from the voiding call; voiding a record whose assignment has since left `VERIFIED_COMPLETED` (e.g. `EXPIRED`) still voids the record but leaves the assignment untouched — `implementation/routes/assignments.py:310-332`
- §3.4 (expiry) — insert — ambiguity — sweep-step-4 expiry also re-evaluates `compliance_blocked` with the attestation cascade (expired cure re-blocks) — `implementation/services.py:364-372`
- §3.5 (extension grant) — revise — ambiguity — the manager's `reason` is internal bookkeeping, not part of the serialized assignment — `implementation/routes/assignments.py:142`, `implementation/response.py:25-27`
- §3.5 (acknowledgement) — revise — ambiguity — the ComplianceAdmin-only null-recipient rule covers any null-recipient notice, including level-2 notices for manager-less employees — `implementation/routes/assignments.py:361-365`
- §3.6 (campaign create) — insert — ambiguity — the regulator must exist but its `status` is not consulted — `implementation/routes/attestations.py:48-49`
- §3.7 (audit report) — revise — ambiguity — regulator `status` not consulted; `role_id`/`manager_id` filters match `current_role_id`/`manager_id` — `implementation/routes/reports.py:32-34`, `implementation/services.py:447-449`

Everything else in the impl (validation priority order, sweep step order and counter keys, boundary inclusivity pins, dedup semantics, posture rule, metrics formulas, endpoint table, error catalogue) was verified to match the PRD as written; no changes needed there. The impl's latest recorded run is 94/94 passing (`implementation/results.8.json`).

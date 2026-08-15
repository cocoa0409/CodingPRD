# Worklog — task_1687_employee_self_service_hr_help_desk

## Step 1: Create Task Directory — 2026-08-14T08:04:00.000Z

Directory tasks/task_1687_employee_self_service_hr_help_desk/ and its workspace/ subdirectory were pre-created and pre-assigned by the pipeline runner. Step 1 treated as DONE per orchestration instructions.

## Step 2: Generate Scaffold — 2026-08-14T09:32:00.000Z

Scaffold generation complete. All three artifacts are written under `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/` and pass lint cleanly.

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/SCAFFOLD.yaml` (965 lines) — §1.0–§1.7 only; no difficulty/corner keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (589 lines) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/SCAFFOLD_CORNER_DESIGN.yaml` (1023 lines) — single top-level key `scaffold_corner_design`

## Counts

- **Entities: 15** — Employee (self-FK manager_id), Team, Agent, TicketCategory, SlaPolicy, KbArticle (self-FK supersedes chain), ArticleView, Ticket, TicketEvent, DataChangeRequest, FraudVerification, SurveyResponse, StaffingWindow, AgentShift, AuditLogEntry
- **Endpoints: 66** (target was 30+)
- **Error codes: 47** (target was 30+); all 47 verified referenced by ≥1 validation/transition/design instance
- **State machines: 9 entries over 7 entities** — cycles on Ticket workflow (RESOLVED→REOPENED→RESOLVED, IN_PROGRESS↔PENDING_EMPLOYEE), KbArticle (DRAFT↔IN_REVIEW rework), DCR fraud (PENDING→FAILED→VERIFIED retry); **parallel dimensions** on Ticket (workflow_status × sla_status) and DataChangeRequest (approval_status × fraud_status); plus SurveyResponse, StaffingWindow, AgentShift, Employee machines
- **Difficulty layers: 4** — optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation (primary archetype: compliance_audit; secondary: workflow_orchestration; role model: segregation_of_duties)
- **§1.8 difficulty instances: 18** (exactly 2 per each of the 9 rules, all §0.5 differentiation clauses honored — e.g., dual variants on Ticket/SLA vs Survey/Agent domains; combinatorial modes (a) min-over-tiers and (b) pinned nested rounding; priority conflicts on state-vs-safety and safety-vs-constraint pairs; half-open vs closed-interval overlap on AgentShift vs StaffingWindow; conserved workload-sum vs KB published-head-count)
- **§1.9 corner instances: 58** (55 active with full recipes + 3 `excluded_because` stubs), spanning all nine claim-guide sections
- **2 OCC concurrency rules** (ticket-assign stale version, DCR-create stale employee version), both §1.2.1-compliant with `${var}`-captured versions

## Verification

- `scaffold_lint.py` final verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (66 endpoints, 15 entities, 18+55 instances, 586 calls scanned; two FK gaps found mid-run were fixed by adding 4 read endpoints)
- Additional mechanical checks passed: all 76 instance names unique across both design files; every `grounds:` reference resolves to a declared §1.1–§1.7 element; no forbidden race vocabulary; enum closure (removed a dead `ADMIN_CORRECTION` value found during audit)
- All formula-derived assert literals were computed with Python before pinning: CSAT dual-variant 3.67 vs 4.26; rounding-order trap 1.21 (pinned) vs 1.22 (naive); deflection 0.6667; attainment 75.0; SLA deadlines (wall 2026-08-01T04:00:00Z vs business-hours 2026-08-03T13:00:00Z across the default-clock Saturday); surge ceil(240×1.5)=360 → 2026-08-01T06:00:00Z; AT_RISK at exactly 360/480 = 0.75
- Logical clock endpoint declared with the mandatory startup default `2026-08-01T00:00:00Z`; all time-gated setups use it (no wall-clock waits)

No sibling task directories were inspected at any point; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-14T09:33:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to tasks/task_1687_employee_self_service_hr_help_desk/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T10:06:00.000Z

All checks pass. The PRD is complete and self-audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/workspace/PRD.md` — 375 lines, generated solely from `SCAFFOLD.yaml` plus the doc-generator skill spec (the two withheld design files were not opened).

**Section structure:**
- §1 Introduction (2 paragraphs, business-pressure framing, `/hr-helpdesk` mount named here only)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (all 8 roles with identity-binding prose per role), 2.2 API Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Resource Identity (incl. the three append-only entities `ArticleView`/`TicketEvent`/`AuditLogEntry` carrying only `id` + `created_at`), 2.5 Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`now_utc`, four sweeps + lazy evaluation), 2.6 Cross-Entity Consistency (flat topology, cascade inventory, left-to-right path validation), 2.7 Confidentiality & Masking (`[REDACTED]`, `masked`), 2.8 Service Calendars & Precision (WALL_CLOCK/BUSINESS_HOURS, ceil-to-minutes, round-half-up precisions), 2.9 OCC (both rules with literal endpoint, `expected_*_version` field, error id, 412), 2.10 Validation Order (all 10 priority tiers in order with error families), 2.11 Segregation of Duties
- §3 Business Logic — 9 subsections (roster → categories/SLA → KB chains → intake/deflection → queue workflow → SLA clock/metrics → DCR+fraud → surveys/coaching → staffing)
- §4 Endpoint table — 66 rows, 4 columns (matches scaffold's 66 endpoints)
- §5 Error catalogue — 47 rows, 2 columns (matches scaffold's 47 errors)

**Self-audit findings:**
- **Contract 1 (Field-Name Coverage): PASS** — 113 required identifiers (all entity fields + endpoint inputs + query/path params, including `q`, `note`, `reason`, `body`, `evidence_code`, `expected_ticket_version`, `expected_employee_version`, `id`), 0 missing. First extraction attempt was thrown off by the §2.2 fenced JSON blocks; stripping fences before tokenizing fixed the measurement (not the document).
- **Contract 2 (Rule Coverage): PASS** — validation priority tiers 1–10 expressed as an ordered narrative; both OCC rules fully specified (endpoint + field + error id + 412); all state-machine transitions expressed with preconditions paired to error ids and side effects (including the reserved `PENDING_APPROVAL` → `PENDING_VERIFICATION` documentation edge, the locked-fraud priority over the generic DCR state error, and the no-new-survey-on-reopen rule); all 6 calculations rendered as precise prose passing the reconstruction test (ceil-after-multiplier SLA deadlines, 0.75 inclusive at-risk fraction vs strict deadline breach, 60-minute deflection link with tie-break, pinned CSAT rounding order with both worked examples 1.21-vs-1.22 and 3.67-vs-4.26, weakest-tier coverage gating with 0.90/1.10 exact comparisons, attainment empty-pool guard); all cascades stated (approve → profile + per-field audit + sibling cancellation; coaching flip → ticket release with `COACHING_RELEASE`; termination → DCR cascade while tickets stay open).
- **Contract 3 (§3 Path Purity): PASS** — 657 backticked tokens scanned in §3, zero paths, zero bare HTTP methods, zero method+path combos; endpoints referenced via state-pair framing and role+verb.
- Additional checks: all 47 error ids appear in §2/§3 prose; all ~60 enum/state values present verbatim; zero fuzzy words ("approximately" etc.) and zero pseudocode operators in backticks; terminal states now stated explicitly for Ticket, DCR, fraud dimension, Survey, KbArticle, StaffingWindow, Employee.
- Information scattering applied: `expected_employee_version` lives in §2.9 while DCR mechanics live in §3.7; `sla_multiplier` defined in §3.9 but consumed in §3.4's deadline computation; address/bank field names introduced in §3.1 but their write path only revealed in §3.7; survey issuance in §3.5 with the CSAT recipe deferred to §3.8; constants embedded in business context (e.g., "seventy-two hours", "at least five days", "sixty minutes", "three-quarters").

## Step 5: Generate Unit Tests — 2026-08-14T11:14:00.000Z

Generation complete. Summary:

### Test counts by queue
- **Queue A (Difficulty): 36 tests** — all 18 instances × 2 tests each. Every `Design: Difficulty/<rule_id>/<instance>` tag resolves.
- **Queue B (Corner): 54 tests** — every non-stub corner instance covered by 1 test, except one deliberate skip (below). Total suite: **90 tests**, all collected cleanly by pytest.

### test_helpers/ (9 files)
`__init__.py` (barrel: framework generics + PRD-specific), `types.py` (11 status/role enums, 17 TypedDicts; append-only ArticleView/TicketEvent/AuditLogEntry omit `updated_at`/`version`), `constants.py` (logical-clock default, SLA_AT_RISK_FRACTION, REOPEN_WINDOW_HOURS, CSAT/staffing/deflection thresholds, `[REDACTED]`), `api_client.py` (ApiClient with 54 endpoint methods), `api_errors.py` (48 error ids + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions, append-only-field checks, `assert_instant_equals` semantic timestamp comparison, event-sequence and workload-conservation invariants), `factories.py` (input-only payload factories), `test_users.py` (opaque-role constants + per-instance builders for the 4 entity-backed roles), `fixtures.py` (clock control, roster/KB/ticket/DCR/staffing composite builders incl. `setup_queue`, `setup_ticket_resolved`, `resolve_and_submit_survey`, fraud-verification helpers).

### test_suite/ (10 files)
`conftest.py` (api + role-header fixtures); `test_01_employee_roster.py` (5); `test_02_kb_lifecycle.py` (9, incl. revision-chain invariant + deflection metrics); `test_03_ticket_intake_sla.py` (13, incl. wall-vs-business clock, surge, at-risk 0.75 boundary); `test_04_ticket_transitions.py` (12, incl. reopen re-anchor cycle, escalation, auto-close); `test_05_assignment_confidentiality.py` (11, incl. OCC, masking, workload conservation); `test_06_data_change_requests.py` (15, incl. fraud retry cycle, sibling-DCR cascade, lockout, SoD); `test_07_surveys_csat.py` (8, incl. pinned rounding 1.21, coaching release cascade); `test_08_staffing.py` (12, incl. min-tier coverage, half-open shifts, closed-interval windows); `test_09_platform_contract.py` (5: pagination, domain-404 sweep, unauthenticated, role denials).

### Instances skipped
- **Corner/state_machines/survey_expiry_on_clock_advance** — the instance asserts a submit after the clock sweep returns `ERR_SURVEY_EXPIRED`, but PRD §3.8 uniquely derives the opposite for that path: "submitting a survey that is already `SUBMITTED`, or one the clock sweep has already moved to `EXPIRED` … fails the state check with `ERR_SURVEY_INVALID_STATE`." Gap left as a gap.
- 3 `excluded_because:` stubs not translated (per spec): `audit_entry_field_level_content` (ref resolves to difficulty instance `dcr_apply_employee_mutation_cancels_sibling_dcr`, which is translated and asserts audit count/dcr_id/change_source); `immediate_read_after_write_employee` and `ticket_create_response_contains_computed_sla` — both refs point at *corner* instances, not difficulty instances (corner-design pointer bug, noted); the cited corner tests are translated and do cover the claims.

### Self-audit findings
- Citation pass: all 90 docstrings carry verbatim PRD quotes (0 grep failures, whitespace-normalized), each ending in exactly one resolving `Design:` line; no skip/xfail/skipif markers anywhere; no "scaffold" references in generated code.
- `employee_creation_defaults_and_immediate_read`: the instance's `version == 1` assertion was dropped — PRD §2.4 says version "increments by one on every mutation" but never pins the initial value (fails the two-reader test); all other defaults (status ACTIVE, has_pending_dcr false, open_ticket_count 0, created_at == logical-clock default) are asserted.
- Timestamp assertions compare parsed instants (`assert_instant_equals`) rather than literal strings, since the PRD pins the instant values but §2.4's "three fractional digits" leaves the zero-fraction rendering of `2026-08-01T00:00:00Z` open to two faithful serializations.
- All collection/compile checks pass against the installed `prd_bench_local_runner.testing` framework.

## Step 6: Generate Implementation — 2026-08-14T11:14:00.000Z

Done. Complete implementation generated and verified.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1687_employee_self_service_hr_help_desk/workspace/implementation/`

**File list (18 files, 3123 total lines):**

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 (flask>=3.0,<4.0) |
| `app.py` | 51 |
| `db.py` | 78 |
| `errors.py` | 67 |
| `response.py` | 35 |
| `middleware.py` | 62 |
| `validate.py` | 206 |
| `serializers.py` | 285 |
| `routes/employees.py` | 149 |
| `routes/teams_agents.py` | 124 |
| `routes/categories.py` | 134 |
| `routes/kb.py` | 241 |
| `routes/tickets.py` | 498 |
| `routes/dcrs.py` | 359 |
| `routes/surveys.py` | 92 |
| `routes/staffing.py` | 204 |
| `routes/audit.py` | 46 |
| `routes/metrics.py` | 88 |
| `routes/clock.py` | 20 |
| `services/sla.py` | 134 |
| `services/csat.py` | 78 |
| `services/deflection.py` | 62 |
| `services/coverage.py` | 50 |
| `services/clocksvc.py` | 49 |

**Endpoint coverage: 66/66** — mechanically cross-checked every row of the PRD §4 endpoint table against Flask's registered URL map; all 66 registered.

**Logical clock & fresh-boot handling:**
- `db.py` holds module-level dicts plus a logical-clock variable initialized to exactly `2026-08-01T00:00:00Z`. All timestamps (created_at, due dates, viewed_at, etc.) come from this clock, never the wall clock. `POST /hr-helpdesk/_clock/set_current_utc` advances it and runs the four sweeps in spec order: SLA re-evaluation → survey expiry → RESOLVED auto-close → staffing-window activation/completion. Ticket `sla_status` is additionally re-evaluated lazily on every ticket read/list.
- Per-test-server fresh boot: storage is pure in-process module state with zero seeding (verified by grep — no `seed_*` anywhere, store empty at boot confirmed live). Each `start.sh` launch gets a pristine empty store.
- `start.sh`: executable, guards the pip install behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, signals propagate). Verified live: `PORT=18999 bash start.sh` serves within ~3s, listens on `0.0.0.0` (reachable via the host's external IP), honors `$PORT`.

**Verification performed** (five ad-hoc smoke suites against fresh boots): full ticket lifecycle (triage/assign-OCC/respond/info loop/escalate selector/resolve/reopen 72h boundary/close/cancel), SLA breach severity chain with exact 0.75 and exact-deadline boundaries, BUSINESS_HOURS weekend walk, surge multiplier from ACTIVE windows, sensitive auto-assign + masking + 403-on-write for STANDARD agents, KB revision-chain atomic supersede + author-cannot-publish SoD, deflection link + rate, DCR fraud flows (SECURITY_CODE lockout after 3 attempts, MANAGER_CONFIRMATION, verifier-cannot-approve, sibling cancellation, audit entries, termination cascade), both PRD-pinned CSAT rounding examples (1.21 and 4.26 reproduced exactly via Decimal half-up with per-term rounding), coaching-hold ticket-release cascade, and staffing coverage posture boundaries (0.90/1.10). One real bug found and fixed during testing (coverage used seconds/60 instead of /3600), plus one ordering fix (assignee clearance is tier-7, before capacity/tier/OCC tier-8).

## Step 7: Run Tests and Iterate — 2026-08-14T11:45:00.000Z

Clean 8-round parallel sweep: **90/90 passed in every round** (720/720 total executions). Exit criteria met.

**Iterations run:** 2 (sweep 1 surfaced 10 deterministic failures — identical set in all 8 rounds; sweep 2 fully clean).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all were fixable as test-side bugs.

**Fixes applied to `test_helpers/`:** none — the fixtures/factories/role-header builders were already PRD-consistent.

**Fixes applied to `test_suite/`:**

- `test_suite/test_06_data_change_requests.py` (5 tests: `test_approve_pending_verification_fraud_required`, `test_self_approval_forbidden`, `test_verifier_cannot_approve`, `test_approve_rejected_dcr_reports_state_error`, `test_approve_rejected_dcr_leaves_request_unchanged`) and `test_suite/test_09_platform_contract.py` (`test_planner_cannot_approve`): removed a spurious `{}` payload positional argument from `api.approve_data_change_request(...)` calls. The api_client method is `(dcr_id, headers)`; the extra arg raised `TypeError` before any assertion ran. PRD §4 defines no request body for the approve endpoint, so the calls now match the declared contract.

- `test_suite/test_04_ticket_transitions.py` (`_resolved_then_clock_to_10`, used by `test_reopen_reanchors_resolution_due_from_reopen_instant`): added a `respond_ticket` call before resolve. Without it, `first_responded_at` stayed null, so after the clock advanced past `first_response_due_at` and the ticket was reopened, PRD §3.6's lazy SLA evaluation (REOPENED + null response + past response deadline) correctly upgraded the observed `sla_status` to `BREACHED_RESPONSE`, breaking the test's `ON_TRACK` assertion. The setup now records a response so the §3.5 "reopen resets `sla_status` to `ON_TRACK`" rule is what's actually exercised.

- `test_suite/test_05_assignment_confidentiality.py` (3 tests): all three were re-assigning from `IN_PROGRESS`, which PRD §3.5 forbids ("Assignment moves a ticket from any of `NEW`, `TRIAGED`, `ESCALATED`, or `REOPENED` to `IN_PROGRESS`" — confirmed against SCAFFOLD's identical from-state list). Fixes:
  - `_two_agent_queue` now builds a **sensitive** category with two `SENSITIVE`-cleared T1 agents, so intake performs the §3.4 sensitive auto-assignment and the ticket opens `NEW` with a1 assigned — `NEW` being both an assignable from-state (§3.5) and a counted state for `assigned_open_count` (§3.1). `test_reassign_moves_open_count_between_agents` and `test_reassign_updates_ticket_assignee_and_version` now re-home a1→a2 directly from `NEW`, so the reassignment genuinely debits/credits the counts and emits the `UNASSIGNED`+`ASSIGNED` pair.
  - `test_occ_stale_ticket_assign_rejected` cycles the ticket through resolve→reopen after the first assign, landing it in `REOPENED` (assignable, still a1's) with the version advanced — so the stale-version attempt is rejected by the tier-8 OCC check (`ERR_STALE_TICKET_VERSION`) rather than the earlier tier-6 state check, per the §2.10 precedence order.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on every failing path (correct state gating on assign, correct lazy SLA severity chain, correct DCR approve gates and precedence). All 10 failures were test-side: one client-signature mismatch and three setups that constructed preconditions the PRD's own rules make unreachable.

## Step 8: Finalize PRD — 2026-08-14T11:55:00.000Z

Step 8 complete. `workspace/PRD_FINALIZED.md` produced via `cp` (Method step 0) and verified byte-identical to `PRD.md` after the verification pass.

**Line counts:** PRD.md = 375 lines, PRD_FINALIZED.md = 375 lines, delta = 0 lines (0.0%). `diff -q` confirms identical.

**Changes:** none. Every `<step_7_diff>` item traced to a verbatim PRD rule that `implementation/` already follows; each failure was a test-side defect (one Python client-signature `TypeError` that never reached the server, three fixtures constructing PRD-unreachable preconditions). No PRD silence and no PRD/impl mismatch was revealed, so the minimal patch is the empty patch.

**Per-item verification log (the pre-edit search for each candidate edit; all concluded "no edit"):**

Item 1 — DCR approve request shape (test_06 ×5, test_09 ×1): (a) Subject: whether `POST /data-change-requests/{id}/approve` accepts/requires a request body. (b) Paths enumerated: `implementation/routes/dcrs.py:254-316` (`approve_dcr` — never calls `get_body()`, consumes zero body fields; gate order: role → 404 → state (line 259) → fraud gate (263) → employee-active (267) → self-approval (270) → verifier-cannot-approve (274)); sibling endpoints for contrast (`verify_dcr` dcrs.py:190 requires `method`; `reject_dcr` dcrs.py:319 requires `reason`; `cancel_dcr` dcrs.py:343 takes no body); `test_helpers/api_client.py:159` (`approve_data_change_request(self, dcr_id, headers)`); `middleware.py:44` (`require_roles`). PRD anchors: §4 preamble, §3.7 approval paragraph (names zero request fields), §2.9, §2.10 tiers 6/7. (c) No wording change: the PRD already uniquely determines an empty approve payload, and the failure was a client-side `TypeError` before any HTTP call — a pure test bug. The one genuinely unpinned question (ignore vs. reject an extraneous body) was never exercised by Step 7, so pinning it would risk inventing behavior — left under-determined per the NO-NEW-MISMATCH rule's preference.

Item 2 — reopen fixture (`_resolved_then_clock_to_10`, test_04): (a) Subject: lazy SLA evaluation of a `REOPENED` ticket with null `first_responded_at` past `first_response_due_at`, and reopen's exact mutation set. (b) Paths enumerated: `implementation/services/sla.py:11-12` (`REOPENED` in `NON_TERMINAL_WORKFLOWS`), sla.py:96-129 (`evaluate_ticket_sla` — `BREACHED_RESPONSE` when `first_responded_at is None and now > fr_due`, severity never heals, `SLA_BREACH` event + version bump on upgrade), sla.py:132-134 (clock sweep), lazy call sites `routes/tickets.py:58-60` (single read) and 175-176 (list, pre-filter), `routes/tickets.py:438-464` (`reopen_ticket` — resets `sla_status`, re-anchors only `resolution_due_at`; leaves `first_response_due_at`/`first_responded_at` untouched), `routes/tickets.py:305-321` (`respond_ticket` stamps `first_responded_at` once). PRD anchors: §3.6 (verbatim severity chain over `NEW…REOPENED`, lazy re-evaluation "on every read of a ticket or the ticket list", no-backwards-healing), §3.5 reopen sentence (exhaustive effect enumeration). (c) No wording change: the observed `BREACHED_RESPONSE`-after-reopen behavior is a direct logical composition of two verbatim PRD rules; the test fix only made the fixture exercise §3.5's reset rather than §3.6's lazy upgrade.

Item 3 — assignment from-states and OCC precedence (test_05 ×3): (a) Subject: assignable from-states, `assigned_open_count` pool membership, UNASSIGNED/ASSIGNED event pair on re-home, state-vs-OCC rejection precedence. (b) Paths enumerated: `implementation/routes/tickets.py:256-302` (`assign_ticket` — from-state check at line 274 = `{NEW, TRIAGED, ESCALATED, REOPENED}`, state rejection before fit checks and the OCC check at line 290, matching §2.10 tier 6 < tier 8; UNASSIGNED emitted only when `prior is not None and prior != agent_id`, then ASSIGNED, lines 297-300), intake auto-assign `tickets.py:128-131`, selector `tickets.py:136-156`, `serializers.py:7-11,40-43` (`AGENT_OPEN_WORKFLOWS` = NEW/TRIAGED/IN_PROGRESS/PENDING_EMPLOYEE/ESCALATED; `TICKET_OPEN_WORKFLOWS` additionally includes REOPENED for the employee-side count), resolve/reopen (tickets.py:388-464) never clear `assigned_agent_id`. PRD anchors: §3.5, §3.1, §3.4, §2.10. (c) No wording change: implementation matches the PRD verbatim on every enumerated path; the fixed tests had constructed preconditions (assign from `IN_PROGRESS`) the PRD's own rules make unreachable.

No new sections added, no prose revised, no behavior invented. A fresh implementer reading `PRD_FINALIZED.md` (identical to `PRD.md`) is already steered to the observed implementation behavior on every path Step 7 touched.

## Step 9: Complete PRD — 2026-08-14T12:20:00.000Z

PRD_COMPLETED.md is produced at `workspace/PRD_COMPLETED.md`. The subagent walked every file in `implementation/` (app, middleware, response, validate, serializers, db, errors, all 11 route modules, all 5 service modules) and pinned every behavior where the PRD admitted multiple readings or contradicted the code. No new sections added; all changes are inline inserts/revisions plus two rows in the existing §5 table.

**Size delta:** PRD_FINALIZED.md 375 lines / 68,353 chars → PRD_COMPLETED.md 377 lines / 72,244 chars (+2 lines, +3,891 chars).

**Counts:** 22 ambiguity-pins, 3 mismatch-revisions (25 edits across 23 diff hunks).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.1 — revise — mismatch — SensitiveCaseManager charter: sensitive-ticket permission is governed by `SENSITIVE` clearance, not role; any agent role holding the clearance may act (was "only agent role permitted") — `implementation/middleware.py:55-62`, `implementation/routes/tickets.py:128-131`.
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_VALIDATION` — `implementation/validate.py:152-172`.
- §2.3 — insert — ambiguity — `has_more` = (`offset` + page size) < `total_count`; filters are exact-match equality; bad boolean filter → `ERR_VALIDATION`; out-of-set enum filter → `ERR_INVALID_ENUM` — `implementation/response.py:25`, `implementation/validate.py:175-194`.
- §2.4 — insert — ambiguity — `version` starts at 1 and `updated_at` equals `created_at` at creation — `implementation/db.py:67-72`.
- §2.5 — insert — ambiguity — clock target `to_iso8601` is not validated against current logical time; clock may move backward — `implementation/routes/clock.py:18-19`.
- §2.7 — insert — ambiguity — caller-side clearance rule binds agent roles only; opaque roles (e.g. `HRServicesAdmin` assigning) are exempt, assignee-side rules still apply — `implementation/middleware.py:55-62`.
- §3.1 — insert — ambiguity — nonexistent `manager_id` → `ERR_EMPLOYEE_NOT_FOUND`; any of the three statuses accepted as initial `status` — `implementation/routes/employees.py:44-46`.
- §3.1 — insert — ambiguity — any unlisted lifecycle transition (incl. self-transitions) → `ERR_EMPLOYEE_INVALID_STATE` — `implementation/routes/employees.py:112-118`.
- §3.3 — revise — mismatch — dropped "optionally attaching a `note`" from return-draft; no note is read or persisted — `implementation/routes/kb.py:158-169`.
- §3.4 — insert — ambiguity — reading an unknown article-view id → `ERR_ARTICLE_NOT_FOUND` — `implementation/routes/kb.py:236-237`.
- §3.5 — insert — ambiguity — triage priority override with no matching policy row → `ERR_SLA_POLICY_NOT_FOUND` — `implementation/routes/tickets.py:239-244`.
- §3.5 — insert — ambiguity — assign check order pinned: assignee clearance → active/capacity → tier match → `expected_ticket_version` last — `implementation/routes/tickets.py:277-292`.
- §3.5 — insert — ambiguity — provide-info requires a free-text `body` — `implementation/routes/tickets.py:347`.
- §3.5 — insert — ambiguity — reopen re-looks-up the policy row; missing row → `ERR_SLA_POLICY_NOT_FOUND` — `implementation/routes/tickets.py:452-455`.
- §3.5 — insert — ambiguity — event shapes pinned: `CREATED` null→`NEW`; `RESPONDED` carries the unchanged current state in both `from_state`/`to_state`; `SLA_BREACH` null/null; `RESOLVED` note carries the `resolution_summary` — `implementation/routes/tickets.py:132,318-319,416`, `implementation/services/sla.py:126`.
- §3.6 — insert — ambiguity — metric endpoints take a required query param; missing/empty → `ERR_VALIDATION`; unknown id → `ERR_CATEGORY_NOT_FOUND`/`ERR_AGENT_NOT_FOUND` — `implementation/routes/metrics.py:16-21,28-29,79-80`.
- §3.7 — insert — ambiguity — 30-day fraud-verification lookback is inclusive at both ends — `implementation/routes/dcrs.py:55-60`.
- §3.7 — insert — ambiguity — verification method is server-chosen: `MANAGER_CONFIRMATION` when the subject has a manager of record, else `SECURITY_CODE` — `implementation/routes/dcrs.py:129`.
- §3.7 — revise — mismatch — `challenge_code` is readable by every role authorized for the listing, including `HRServicesAdmin` (was: only owner + `HRDataSteward`) — `implementation/serializers.py:214-225`, `implementation/routes/dcrs.py:175-187`.
- §3.7 — insert — ambiguity — verify against a `NOT_REQUIRED` request → `ERR_DCR_INVALID_STATE`; verify naming the non-issued method → `ERR_VALIDATION`, both ahead of the evidence comparison — `implementation/routes/dcrs.py:212-218`.
- §3.8 — insert — ambiguity — `COACHING_RELEASE` event's `actor_user_id` is the employee whose survey submission triggered the cascade — `implementation/services/csat.py:76`, `implementation/routes/surveys.py:91`.
- §3.9 — insert — ambiguity — window overlap is tested only against `PLANNED`/`ACTIVE` windows; `COMPLETED`/`CANCELLED` never conflict — `implementation/routes/staffing.py:45-50`.
- §3.9 — insert — ambiguity — a clock jump landing past `window_end` of a still-`PLANNED` window leaves it `PLANNED`; only `ACTIVE` windows complete — `implementation/services/clocksvc.py:32-39`.
- §5 — insert — ambiguity — added catalogue rows `ERR_AUDIT_ENTRY_NOT_FOUND` (404) and `ERR_NOT_FOUND` (404) with a clause pinning unknown-audit-id and undeclared-path/method rejections — `implementation/routes/audit.py:45`, `implementation/app.py:32-38`, `implementation/errors.py:60-62`.

All other implementation behaviors (envelope shape, validation tier ordering, SLA math incl. business-hours walk and surge rounding, deflection link window/tie-break, sensitive auto-assign selector, escalation selector, CSAT pinned rounding with both worked examples verified against the code, coaching cascade, coverage ratios/posture thresholds, OCC placement, segregation-of-duties ordering, termination/apply cascades) were already uniquely pinned by the PRD and left untouched.

## Post-Step-9 Verification Re-Sweep — 2026-08-14T12:45:00.000Z

Orchestrator note: the Step 7 subagent's `results.{1..8}.json` artifacts were not present in `workspace/implementation/` at final verification (likely cleaned up by the subagent after parsing). The orchestrator re-ran the full 8-round parallel stability sweep itself (bash, no subagent; identical command to Step 7's iteration step). Result: **8/8 rounds clean — 90/90 passed, 0 failed, 0 errors, 0 skipped in every round (720/720 executions)**; each round ~117s. The `results.{1..8}.json` files from this sweep are retained in `workspace/implementation/` as evidence. No code or document changes resulted; the final state is confirmed green.

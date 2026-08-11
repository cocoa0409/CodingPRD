# Worklog — task_1164_appellate_deadline_brief_production

## Step 1: Create Task Directory — 2026-08-11T06:33:00.000Z

Pre-assigned output folder `tasks/task_1164_appellate_deadline_brief_production` with `workspace/` subdirectory already exists (per headless-run instructions). Step 1 auto-index scan skipped; directory treated as created.

## Step 2: Generate Scaffold — 2026-08-11T07:15:00.000Z

All three files exist on disk and lint is clean.

## Summary

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1164_appellate_deadline_brief_production/`):

- `SCAFFOLD.yaml` — 84,992 bytes
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 99,161 bytes
- `SCAFFOLD_CORNER_DESIGN.yaml` — 94,875 bytes

**Counts (SCAFFOLD.yaml):**
- Entities: 16 (Court, Case, Attorney, AppealEvent, Deadline, Record, TranscriptOrder, BriefingSchedule, Brief, TableOfAuthorities, Citation, ExtensionMotion, Filing, OralArgument, Decision, FurtherReviewPetition)
- State machines: 9 (Record, TranscriptOrder, Brief, BriefingSchedule, ExtensionMotion, Filing, OralArgument, FurtherReviewPetition, Case)
- Endpoints: 85 (includes `/_clock/set_current_utc` and `/_clock/current_utc` test-driving endpoints)
- Errors: 21
- Calculations: 9 | Validations: 18 | Roles: 4 | Concurrency rules (OCC): 2

**Difficulty design (§1.8):** 9 rule_ids × 2 instances each = 18 instances (meets the ≥18 minimum). Each rule instance satisfies §0.5's differentiation clause (different entity domains, error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities, trigger types).

**Corner design (§1.9):** 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model) covering 36 instances — 34 active + 2 `excluded_because` stubs that reference §1.8 difficulty instances.

**Lint verdict:**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Harder-than-expert density mechanisms applied:** dual-variant calculations on two distinct entity domains (Deadline provisional/final vs Brief word/page variants); depth-3 transitive cascade (motion grant → schedule shift → brief re-derivation → deadline recompute); cyclic state machine (Brief DRAFT↔IN_REVIEW) + compound Case posture derived from child states; cross-entity gating (Brief↔Record, Petition↔Decision); two OCC concurrency rules on different parents (Case, BriefingSchedule); segregation-of-duties role model (brief approver must differ from author); half-open interval overlap on court calendar vs stacked-deadline interval semantics on attorney calendar; compensating invariants on Brief.status distribution and Deadline.met flag.

## Step 3: Copy Shared Files — 2026-08-11T07:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1164_appellate_deadline_brief_production/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T07:26:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1164_appellate_deadline_brief_production/workspace/PRD.md`.

**File stats:** 56,210 bytes, 326 lines.

**Sections:** 1. Introduction; 2. Global Specifications (2.1 RBAC, 2.2 API Response Structure [verbatim fixed block], 2.3 Pagination, 2.4 Resource Identity & Common Fields, 2.5 The Logical Clock, 2.6 Optimistic Concurrency Control, 2.7 Calendar Arithmetic & Precision, 2.8 Nested Resources & Cascades, 2.9 Validation Pipeline & Priority Order); 3. Business Logic (3.1–3.8, lifecycle-organized: registration → case opening/tolling → record/transcripts → schedule/extensions → briefs/TOA → clerk filing review → oral argument → decision/further review); 4. Endpoint Definitions (85-row, 4-column table); 5. Error Code Catalogue (21-row, 2-column table).

**Hard-contract results (all PASS):**
- **Contract 1 (Field-Name Coverage):** 89/89 entity fields, 62/62 endpoint input identifiers, 25/25 query params present verbatim in backticks; all 21 error IDs, all 4 role names, all 35 state values, and all 85 enum values present. One typo found during verification (`file_at` → `filed_at`) was fixed.
- **Contract 2 (Rule Coverage):** All 18 validations expressed with explicit priority ordering in §2.9 plus endpoint-local orderings in §3 (approve, efile, grant, schedule, petition-file); both OCC rules stated with `expected_case_version`/`expected_schedule_version`, mismatch → `ERR_STALE_VERSION` 412, framed in stale-observation terms; all 9 state machines with every transition's from/to, preconditions, and side effects; all 9 calculations as precise prose (tolling delta, forward-anchored schedule dates with chronological multi-motion ordering, strict-greater dual-variant limit check, floor-division completeness, 14/30/90 rehearing/cert windows, half-open overlap with adjacency allowed, depth-limited extension cascade with invariant); all endpoint side effects and `applies_to` scopes covered; constants embedded in business context (30/60 appeal days, 40/30 brief windows, 30-day transcript delivery, 14-day argument notice, 14/30/90 petition windows).
- **Contract 3 (§3 Path Purity):** 547 backticked tokens scanned in §3, zero paths, zero bare HTTP methods, zero method+path tokens.

One scaffold ambiguity handled faithfully: the Record `COMPLETE → FILED` transition precondition ("filing accepted") conflicts with the endpoint side effect ("creates Filing … status=SUBMITTED"); the PRD states both clauses literally (record filing moves to `FILED` and creates a `SUBMITTED` filing; clerk acceptance of a `RECORD` filing also drives the record to `FILED`) without inventing a reconciliation. The constraint files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) and sibling task directories were not accessed.

## Step 5: Generate Unit Tests — 2026-08-11T07:58:00.000Z

Generation complete. All verification passed.

## Files written

**`test_helpers/`** (9 files, all required modules present):
- `__init__.py` (841 B) — barrel export of framework generics + PRD-specific code
- `types.py` (8.0 KB) — 16 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version`), 17 status/role enums
- `api_client.py` (13.7 KB) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~70 methods) + singleton
- `api_errors.py` (2.2 KB) — 21 `ApiErrorId` values + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (7.8 KB) — per-entity `assert_*` checkers + instant-safe timestamp helpers (`parse_ts`/`add_calendar_days`/`assert_instant_equal`, format-agnostic per §2.7) + `find_deadline`, `assert_schedule_dates_ordered`
- `factories.py` (4.4 KB) — payload factories, input fields only
- `constants.py` (1.2 KB) — PRD-named thresholds (40/30 schedule windows, 30-day transcript window, 14-day notice, 14/30/90 rehearing windows, pagination bounds)
- `test_users.py` (1.4 KB) — shared constants for the 3 opaque roles + `make_attorney_headers(id)` builder for the entity-backed Attorney role
- `fixtures.py` (15.8 KB) — composite setups: `setup_record_pending_case`, `setup_briefing_case` (notice → designate → transcript delivery → COMPLETE/ACTIVE), brief lifecycle walkers (READY/EFILED/ACCEPTED), `setup_argument_pending_case` (reply-window clock advance), `setup_decided_case` (waive + decision entry honoring the PRD §3.8 "argument must stand HELD or WAIVED" entry requirement)

**`test_suite/`**: `conftest.py` + 10 numbered test files, **72 test functions total** (36 Difficulty-tagged, 36 Corner-tagged).

## Coverage vs design indices
- **§1.8 Difficulty: 18/18 instances covered, each with ≥2 tests** (36 tests). Notable translation choices: `business_temporal_vs_business_constraint_late_overlimit` — the instance's own recipe discovered that READY+over-limit+late is unreachable via PRD endpoints (approve gates on `over_limit`, PATCH is DRAFT/IN_REVIEW-only), so I translated its actual asserted outcome (priority-5 state gate fires first on efile of a DRAFT brief, with late+over-limit also true) plus an isolated single-failure companion. `transcript_delivery_deadline_vs_record_designation_window` — the stacked-conflict claim depends on `Record.designation_due_at`, whose formula the PRD never states (fails unique-derivability); I translated only the verbatim-derivable half (`due_at = ordered_at + 30 days`, §3.3), as two tests including time-of-day preservation.
- **§1.9 Corner: 32/34 non-stub instances covered** (both `excluded_because` stubs correctly untranslated; cross-references resolve). **2 skipped** (gaps left as gaps, no placeholders):
  1. `state_machines/extension_motion_withdraw_precondition_lead_attorney_only` — PRD §3.4 says "withdrawal by anyone else is forbidden" but names **no error_id**; two PRD-only readers could plausibly return `ERR_FORBIDDEN_ROLE`, `ERR_INVALID_STATE`, or another 4xx. Fails unique derivability.
  2. `consistency_model/immediate_consistency_read_after_write` — the PRD contains **no verbatim consistency-model statement** (the claim grounds only in the scaffold's `complexity_profile`). Fails coverage.

## Verification
- `python3 -m py_compile` clean on all 20 `.py` files (9 helpers + conftest + 10 test files).
- All 10 test modules + conftest import successfully (no unresolved names against `test_helpers`).
- Tag audit: every test has exactly one `Design:` line; all tags resolve to real instances; no stub tagged; no dual/untagged tests.
- Citation audit: 76 unique quoted PRD strings extracted from docstrings — **all 76 survive literal whitespace-normalized grep of PRD.md** (C1/C2/C3 satisfied).

One design-index bug worked around in translation: `brief_cyclic_review_loop` and `case_parallel_state_dimensions_*` recipes referenced an undefined capture (`attorney_a_id`) and approved briefs with the authoring attorney (which PRD §3.5 segregation-of-duties forbids); my translations use the created lead attorney and a separate admitted reviewer attorney instead, preserving each instance's asserted outcomes.

## Step 6: Generate Implementation — 2026-08-11T07:58:00.000Z

Implementation complete. Summary:

## Files written (26 files, in `workspace/implementation/`)

- `start.sh` (396 B, executable) — guarded foreground launcher: installs Flask only if missing, then `exec python3 app.py`
- `requirements.txt` (16 B) — `flask>=3.0,<4.0`
- `app.py` (1.7 KB) — Flask app factory, blueprint registration, ApiError + 400/404/405 handlers
- `db.py` (2.5 KB) — in-memory `Store` (16 dicts, all empty at boot), logical clock pinned at `2026-05-01T00:00:00.000Z`, ISO8601 ms-precision helpers, UUID/confirmation/request-id generators
- `errors.py`, `response.py`, `middleware.py` — 21-error catalog, the exact `meta`/`response_type`/`data` envelope with pagination fields, and `X-User-ID`/`X-User-Role` auth with the 4 roles
- `services/core.py` (16.6 KB) — payload/pagination/FK validators, calendar arithmetic (calendar-day add, weekend/holiday rollforward with US federal court holidays), brief-limit/TOA/completeness aggregations, schedule-date computation with chronological extension cascade
- `services/workflows.py` (18.9 KB) — cross-entity cascades: case opening (auto JUDGMENT_ENTERED event + NOTICE_OF_APPEAL deadline), event tolling, record completion → schedule activation → posture transitions, filing accept/reject cascades, decision entry, petition grant/deny
- `routes/*.py` — 15 blueprint modules covering every resource group

## Verification results

- **Routes: 85/85** (method, path) pairs registered — exactly matching SCAFFOLD.yaml §1.5 (Flask's built-in `/static` route disabled via `static_folder=None`); orchestrator independently re-verified with normalized placeholder comparison: 85 scaffold endpoints vs 85 impl routes, 0 missing, 0 extra.
- **py_compile**: all 24 `.py` files pass
- **Boot check**: `PORT=18799 timeout 8 bash start.sh` → clean boot, `Running on all addresses (0.0.0.0)`, no tracebacks (exit 124 = expected timeout kill)
- **Live smoke test** verified end-to-end: unauthenticated → `ERR_UNAUTHENTICATED`; clock boot value `2026-05-01T00:00:00.000Z`; court duplicate → `ERR_DUPLICATE`; case create computes NOA deadline (judgment 2026-04-01 + 30d = 2026-05-01, no rollforward needed); post-judgment tolling shifts `final_due_at` +15 days; notice-filing acceptance cascades (posture OPEN→RECORD_PENDING, Record + BriefingSchedule auto-created); transcript delivery completes record (pct 100) and activates schedule (opening 06-10 / response 07-10 / reply 07-31 with correct 40/30/21-day anchoring); brief segregation-of-duties → `ERR_SELF_APPROVAL_FORBIDDEN`; extension grant with stale `expected_schedule_version` → `ERR_STALE_VERSION`, correct version cascades +5 days to all three schedule dates and brief `due_at`; e-file → filing accept marks brief ACCEPTED and deadline met; pagination bounds → `ERR_PAGINATION`; RBAC → `ERR_FORBIDDEN_ROLE`; unknown id → `ERR_NOT_FOUND`.

No seeding, no disk persistence — store starts empty on every boot, satisfying the per-test-server isolation contract.

## Step 7: Run Tests and Iterate — 2026-08-11T08:10:00.000Z

All 8 rounds pass 72/72 with zero failures and zero errors. The sweep is clean.

## Summary

**Iterations run:** 2 (first sweep: 13 deterministic failures × 8 rounds; second sweep: all 8 rounds clean, 72/72 each).

**Tests deleted:** none. One test was narrowed per the partial-coverage rule (1c) rather than deleted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_motion()` gained `**overrides` forwarded to `create_extension_motion_payload`. Why: `test_grant_with_stale_schedule_version_returns_stale_version` passes `reason="first"`/`reason="second"` (PRD §3.4 names `reason` as a motion payload field), and the fixture's fixed signature raised `TypeError` before any request was issued. This unblocked 1 test.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_record_and_transcripts.py` — `test_revoke_designation_cancels_open_transcripts` narrowed. The original drove the record to ASSEMBLING (via `begin_preparation`) before revoking; PRD §3.3 states the transition only as "revoking a designation moves the record from `DESIGNATED` back to `PENDING_DESIGNATION`", and a faithful PRD-only implementer can legitimately reject revocation from ASSEMBLING (the current implementation does exactly that) — success-from-ASSEMBLING is not uniquely derivable. The covered half was kept verbatim: revoke from DESIGNATED with two ORDERED transcripts still asserts record → PENDING_DESIGNATION, `designated_at` → null, and every ORDERED transcript → CANCELLED.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/workflows.py` — added `reconcile_case(case)`, which runs the two clock-driven transitions the PRD defines: `maybe_complete_schedule` (§3.4: ACTIVE → COMPLETE once opening+response briefs are ACCEPTED and the reply window has passed, driving posture BRIEFING → ARGUMENT_PENDING and auto-creating the REQUESTED oral argument) and the existing `maybe_close_case` (§3.8: DECIDED → CLOSED at mandate). PRD §2.5 ("advancing the clock … changes only what 'now' means for every rule evaluated afterwards") and §3.8 ("always readable as the case's computed `posture`") require these rules to be evaluated lazily after a clock advance.
- `workspace/implementation/routes/cases.py` — `get_case` / `list_cases` now call `reconcile_case` (previously only `maybe_close_case`, which missed schedule completion).
- `workspace/implementation/routes/schedules.py` — `get_case_schedule` / `get_schedule` reconcile the parent case before reading.
- `workspace/implementation/routes/arguments.py` — `schedule_argument` reconciles before the ARGUMENT_PENDING posture gate.
- `workspace/implementation/routes/petitions.py` — `file_petition` reconciles before the deadline-currency/decision-issued checks.

These implementation fixes resolved the 11-test cluster where the posture stayed BRIEFING after the clock passed `reply_due_at` (all of test_08's four overlap/adjacency tests and test_09's seven rehearing-window/posture-arc/petition-gate tests failed in setup on that single root cause). No endpoint, field, or side effect was added beyond what PRD §2.5/§3.4/§3.8 state; storage remains in-memory only.

**Orchestrator disk verification:** all 8 `results.{1..8}.json` files present; each reports passed=72 total=72 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-11T08:18:00.000Z

Done. `workspace/PRD_FINALIZED.md` is written with 4 inline edits, all traced to `<step_7_diff>` items.

## Size delta
- PRD.md: 326 lines / 55,981 chars → PRD_FINALIZED.md: 326 lines / 57,354 chars (+2.45% chars; line count unchanged — all edits are inline within existing paragraphs, no new sections).

## Changes
- §2.5 — revise — appended lazy-evaluation semantics for the two purely time-driven transitions (schedule completion, mandate closure): evaluated when the affected case or briefing schedule is fetched/listed, and before the posture/deadline gates on argument scheduling and petition filing — `implementation/services/workflows.py:266-278` (`reconcile_case`), `routes/cases.py:31,43`, `routes/schedules.py:26,39`, `routes/arguments.py:83-84`, `routes/petitions.py:122-123`
- §3.4 — revise — pinned that schedule completion is evaluated on brief-filing acceptance and lazily per §2.5; the schedule does not leave ACTIVE at the instant the reply window closes — `implementation/services/workflows.py:239-263` (`maybe_complete_schedule`), `:334` (event-driven call from `accept_filing`)
- §3.3 — revise — pinned revocation source-state gate: transition exists only from DESIGNATED; from ASSEMBLING/COMPLETE → ERR_INVALID_STATE, from FILED → ERR_ALREADY_TERMINAL — `implementation/routes/records.py:72-80`
- §3.8 — revise — pinned that DECIDED→CLOSED mandate closure is applied lazily per §2.5, not at the instant the mandate issues — `implementation/services/workflows.py:53-69` (`maybe_close_case`)

No edit for the `test_helpers/fixtures.py` `create_motion(**overrides)` item: PRD §3.4 already pins `reason` as a motion payload field and `routes/motions.py:33` requires it — pure fixture bug, no PRD silence.

## Per-edit pre-edit search log

**Edit 1 (§2.5, lazy evaluation).** (a) Subject: when/where time-driven transitions are evaluated. (b) Enumerated: `workflows.py:239 maybe_complete_schedule`, `:53 maybe_close_case`, `:266 reconcile_case`; all reconcile callsites via repo-wide grep — `cases.py:31,43`, `schedules.py:26,39`, `arguments.py:84`, `petitions.py:123`, plus event-driven `workflows.py:334`; non-reconciling paths checked: `clock.py` (both endpoints), `decisions.py:17 create_decision` (gates on argument HELD/WAIVED, no reconcile), `briefs.py:151 submit-review` (posture gate, no reconcile), `records.py:41 designate` (posture gate, no reconcile), argument/deadline/record/petition reads (no reconcile). (c) Wording scoped to "the affected case or briefing schedule is fetched or listed" (all four such reads do reconcile) and named only "argument scheduling and petition filing" for writes — deliberately avoiding a universal "any posture-gated write" claim that submit-review/designate/create_decision would falsify; used "posture and deadline gates" (not "state checks") because the petition/argument's own state checks run before reconcile while the case-level gates run after.

**Edit 2 (§3.4, completion evaluation timing).** (a) Subject: when schedule completion fires. (b) Enumerated: `maybe_complete_schedule` (condition: ACTIVE + OPENING/RESPONSE ACCEPTED + (REPLY ACCEPTED or now strictly > reply_due_at); effects: COMPLETE, posture BRIEFING→ARGUMENT_PENDING, auto-create REQUESTED argument); both invocation sites (`accept_filing` brief-acceptance path, `reconcile_case`); confirmed `clock.py` set endpoint triggers nothing. (c) "has passed reply_due_at" kept verbatim (matches strict `>`); added only evaluation-timing clause.

**Edit 3 (§3.3, revocation source state).** (a) Subject: record revocation source states. (b) Enumerated every record-status writer: `records.py:41 designate_record`, `:68 revoke_designation`, `:94 file_record`, `transcripts.py:99-101 begin_preparation` (DESIGNATED→ASSEMBLING), `workflows.py:176 maybe_complete_record` (ASSEMBLING→COMPLETE), `workflows.py:370-374 accept_filing` RECORD (COMPLETE→FILED). No path moves a record backward into DESIGNATED. (c) Initial draft said "ASSEMBLING or beyond → ERR_INVALID_STATE"; revised because FILED is "beyond" yet yields ERR_ALREADY_TERMINAL (`records.py:72-73`) — final wording names ASSEMBLING/COMPLETE for ERR_INVALID_STATE and FILED separately for ERR_ALREADY_TERMINAL.

**Edit 4 (§3.8, closure timing).** (a) Subject: when DECIDED→CLOSED is applied. (b) Enumerated: `maybe_close_case` (requires DECIDED, latest decision by `_seq` with non-null mandate_at, no DRAFT/FILED petitions, `now >= mandate_at`); `deny_petition` (`workflows.py:468-486`) closes immediately on denial when no petitions remain — event-driven, already pinned by existing PRD text; `grant_petition` CERTIORARI→CLOSED — also already pinned. (c) None needed; "reaches mandate_at" already matches `>=`; addition only states lazy application.

## Step 9: Complete PRD — 2026-08-11T08:35:00.000Z

All edits are in place — 33 single-paragraph hunks, all inline. Line count unchanged at 326; char delta +4676 (byte delta +4733). Here is the summary.

## Summary

**Files:** `PRD_FINALIZED.md` (326 lines / 57,354 chars) → `PRD_COMPLETED.md` (326 lines / 62,030 chars), delta **+4,676 chars** (+4,733 bytes), 0 lines added/removed — all changes are in-paragraph inserts or revisions. No new sections.

**Counts:** 37 ambiguity-pins (insert), 11 mismatch-revisions (revise).

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also rejected with `ERR_PAGINATION` — services/core.py:106-126
- §2.3 — insert — ambiguity — list sort ties on `created_at` break by creation order (`_seq`) — services/core.py:129-131
- §2.3 — insert — ambiguity — boolean filters (`met`, `verified`) accept `true`/`1`/`false`/`0` case-insensitively; other values ignored — routes/deadlines.py:18-27, routes/toas.py:74-79
- §2.5 — insert — ambiguity — clock-set responds HTTP 200 with the new value as `current_utc` — routes/clock.py:15-28
- §2.5 — insert — ambiguity — all entity timestamps (`created_at`, `updated_at`, `filed_at`, …) read the logical clock; only `meta.api_request_timestamp` is wall-clock — db.py:21-36, services/core.py:253-267
- §2.7 — insert — ambiguity — "court holiday" defined as US federal holidays with Fri/Mon observance of weekend fixed-date holidays — services/core.py:280-345
- §2.8 — insert — ambiguity — body reference existing but parented to another case yields `ERR_FK_NOT_FOUND` — routes/briefs.py:42-44, routes/petitions.py:32-34, routes/motions.py:36-38
- §2.9 (rule 7) — insert — ambiguity — `X-User-ID` resolving to no attorney record treated as not admitted (`ERR_NOT_ADMITTED`) — routes/briefs.py:47-50,177-179,230-232; routes/petitions.py:36-38
- §2.9 (rule 18) — insert — ambiguity — case `docket_number` uniqueness within court yields `ERR_DUPLICATE` — services/workflows.py:86-90
- §2.9 (final para) — insert — ambiguity — all narrative-named payload fields required; value-range rules (positive `requested_days`/`duration_minutes`/`actual_pages`, non-empty `reason`) fail with `ERR_INVALID_REQUEST` — services/core.py:33-99, routes/motions.py:34-35, routes/arguments.py:30-31, routes/transcripts.py:119-122
- §3.1 — insert — ambiguity — `admitted_court_ids` stored as supplied, no reference validation — routes/attorneys.py:25,31-36
- §3.2 — insert — ambiguity — `RECORD_DESIGNATION`/`TRANSCRIPT_ORDER` deadlines' provisional and final dues equal the accepted notice filing's `filed_at` — services/workflows.py:364-368
- §3.3 — insert — ambiguity — `CANCELLED` orders do not block designation — routes/records.py:52-55
- §3.3 — insert — ambiguity — record stamps `completed_at` on completion — services/workflows.py:188
- §3.3 — insert — ambiguity — briefing deadline rows' dues equal schedule `opening/response/reply_due_at` — services/workflows.py:222-232
- §3.3 — insert — ambiguity — record filing created with `method` `EFILE`, empty `served_party_emails` — routes/records.py:106
- §3.4 — insert — ambiguity — grant check order pinned: motion state → grant-days → schedule `ACTIVE` → stale-version — routes/motions.py:122-136
- §3.4 — insert — ambiguity — grant recomputes `final_due_at` only for the target's deadline kind, summing all granted motions whose cascade reaches it; other kinds untouched — routes/motions.py:175-190
- §3.4 — insert — ambiguity — motion withdrawal by non-lead rejected with `ERR_FORBIDDEN_ROLE` — routes/motions.py:224-227
- §3.4 — insert — ambiguity — auto-created oral argument has `scheduled_start`/`duration_minutes`/`panel_judges` unset — services/workflows.py:254-263
- §3.5 — insert — ambiguity — `AMICUS` brief inherits `opening_due_at` — services/core.py:499-504
- §3.5 — insert — ambiguity — non-author submit rejected with `ERR_FORBIDDEN_ROLE`, checked after state check and before posture check — routes/briefs.py:146-153
- §3.5 — insert — ambiguity — `normalized` citation = trim + collapse whitespace runs — routes/toas.py:19-21
- §3.5 — insert — ambiguity — verifying an already-verified citation → `ERR_INVALID_STATE` — routes/toas.py:92-93
- §3.5 — insert — ambiguity — e-file response carries the created filing row — routes/briefs.py:259-265
- §3.6 — insert — ambiguity — "serve all adverse parties" enforced as non-empty `served_party_emails` — routes/filings.py:38-44
- §3.6 — insert — ambiguity — BRIEF acceptance leaves a non-`EFILED` brief unchanged — services/workflows.py:315-317
- §3.6 — insert — ambiguity — NOTICE_OF_APPEAL cascades run only while posture is `OPEN`; otherwise only the filing's status changes — services/workflows.py:336-337
- §3.6 — insert — ambiguity — RECORD acceptance moves record to `FILED` only from `COMPLETE` — services/workflows.py:370-374
- §3.6 — insert — ambiguity — petition-filing acceptance is a status-only no-op (petition already `FILED`); `EXTENSION_MOTION` acceptance has no cascade — services/workflows.py:376-379
- §3.7 — insert — ambiguity — manual argument re-request accepted in any posture; `ARGUMENT_PENDING` gate applies at scheduling — routes/arguments.py:22-44
- §3.7 — insert — ambiguity — waive by non-lead → `ERR_FORBIDDEN_ROLE` (403) — routes/arguments.py:185-188
- §3.7 — insert — ambiguity — log-moot on terminal argument → `ERR_ALREADY_TERMINAL` — routes/arguments.py:201-202
- §3.8 — insert — ambiguity — `mandate_at` equals `rehearing_deadline_at` (mandate issues at rehearing-window close) — services/workflows.py:405-409
- §3.8 — insert — ambiguity — auto-created decision deadlines due at `rehearing_deadline_at` and `issued_at`+90d respectively — services/workflows.py:423-429
- §3.8 — insert — ambiguity — petition filing row created with `method` `EFILE`, empty `served_party_emails` — routes/petitions.py:134-135
- §3.8 — insert — ambiguity — any `Attorney` may withdraw a `DRAFT` petition (petitions record no author); denial recomputes the most recently entered decision — routes/petitions.py:171-184, services/workflows.py:474-481

### Mismatch-revisions (PRD described different behavior → revised to impl)

- §3.3 — revise — mismatch — `designation_due_at` is never computed; stays null — services/workflows.py:346
- §3.3 — revise — mismatch — transcript orders allowed under any non-`FILED` record (not only designated records); `FILED` → `ERR_ALREADY_TERMINAL` — routes/transcripts.py:32-33
- §3.3 — revise — mismatch — transcript delivery window fixed at 30 days (no per-court override exists) — routes/transcripts.py:19,39
- §3.4 — revise — mismatch — opening/response windows fixed at 40/30 days for every court (not "by default") — services/core.py:454-455,459-460
- §3.5 — revise — mismatch — brief-creation admission checks the acting attorney (`X-User-ID`), not the named author — routes/briefs.py:46-51
- §3.5 — revise — mismatch — no TOA "generation pass" exists; `generated_at` stays null, counts maintained incrementally — routes/toas.py:44-103, routes/briefs.py:69-76
- §3.5 — revise — mismatch — any `Attorney` (not only the author) may PATCH page/word counts in `DRAFT`/`IN_REVIEW` — routes/briefs.py:109-131
- §3.5 — revise — mismatch — striking a brief leaves case posture unchanged (no recompute) — routes/briefs.py:268-294
- §3.7 — revise — mismatch — argument notice window fixed at 14 days (no per-court setting) — routes/arguments.py:19,116
- §3.8 — revise — mismatch — petition denial uses a zero-day mandate delay (`mandate_at` = denial instant), not a court-configured setting — services/workflows.py:479-481
- §4 — revise — mismatch — the three 1:1 fetch endpoints (`cases/{id}/record`, `cases/{id}/briefing-schedule`, `briefs/{id}/toa`) return the paginated array envelope, not a bare object — routes/records.py:20-27, routes/schedules.py:21-29, routes/toas.py:24-31

**Verification:** full diff reviewed — 33 hunks, each confined to a single existing paragraph line; no sections added or removed; no behavior invented beyond what `implementation/` exhibits.

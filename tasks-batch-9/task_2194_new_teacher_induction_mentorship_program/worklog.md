# Worklog — task_2194_new_teacher_induction_mentorship_program

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2194_new_teacher_induction_mentorship_program/` and `tasks/task_2194_new_teacher_induction_mentorship_program/workspace/` (name pre-allocated by the invoking command; no index scan performed).

## Step 3: Copy shared files — 2026-08-31T18:05:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2194_new_teacher_induction_mentorship_program/workspace/INSTRUCTION.md` (1424 bytes). Run out of order (ahead of Step 2's completion) because it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-08-31T20:30:00.000Z

First attempt (background subagent) died to a stream watchdog ("no progress for 600s") having written zero files; it stalled on its opening action. Relaunched with two mitigations: read the 774-line SKILL.md in ~200-line slices rather than one call, and cap each Write at ~300 lines so the agent keeps emitting tool calls instead of going silent through a long generation. Retry succeeded.

Subagent summary (verbatim):

All three artifacts are complete and the official lint is clean on the first run.

Lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1204

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Deliverables

- `SCAFFOLD.yaml` — 3299 lines. 13 entities, 12 state machines (5 entities, `NoviceTeacher` and `ObservationCycle` carrying two parallel state dimensions each), 3 OCC rules, 9 calculations, 54 validations, 59 endpoints, 70 errors, 5 roles. Profile: `compliance_audit` × `graph_constraint`, layers `[selector_policy, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency, `difficulty_level: beyond_expert`. No `scaffold_*_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2097 lines, single top-level key, 9 rules × 2–3 instances = 20 instances (min 2 per rule, >=18 total satisfied).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4367 lines, single top-level key, all 9 claim-extraction-guide sections, 85 instances (68 with full `test_recipe`, 17 `excluded_because:` stubs), 62 distinct guide-sanctioned `claim_type` values, zero name collisions with §1.8.

Self-consistency defects found and repaired in SCAFFOLD.yaml while replaying chains

- p40 (duplicate disbursement period) was scoped over `{DRAFT, APPROVED, PAID}`, which made the declared `StipendDisbursement DRAFT -> SUPERSEDED` transition, the `SUPERSEDED` enum and `superseded_by_id` unreachable. Re-scoped to `{APPROVED, PAID}` with matching edits to the error condition.
- p18 required `ACTIVE` for packet creation, but packet creation itself bubbles the novice `ACTIVE -> COMPLETION_PENDING`, so `ERR_ACTIVE_PACKET_EXISTS` (p41) was unreachable — every second attempt returned the program-state error instead. p18 now admits `COMPLETION_PENDING` for packet creation and defers to p41; the rbac/errors instances assert precisely that the 409 is `ERR_ACTIVE_PACKET_EXISTS` and not `ERR_NOVICE_PROGRAM_STATE_INVALID`.
- `CompletionCertification RETURNED -> WITHDRAWN` claimed a `COMPLETION_PENDING -> ACTIVE` novice hop plus a `NoviceTeacher.version` bump, but the preceding RETURN had already moved the novice to ACTIVE; that path now explicitly leaves the novice untouched and bumps only the packet version, contrasted with the `ASSEMBLING -> WITHDRAWN` hop.
- Two payloads used a non-existent `contact_type` (`IN_PERSON_COACHING`) and a wrong rate (7000 vs the declared EXACT rate of 4200 cents/hour); corrected to `CO_PLANNING` / 4200, and all contact-type and attendance-status literals across both design files were swept against the declared enums.

RBAC-denial claims (`ERR_FORBIDDEN_ROLE`, `ERR_UNAUTHENTICATED`) are deliberately expressed as `assert:` prose rather than trigger calls, because lint check (b) rejects any call whose `as:` role is not listed on that endpoint in §1.5; the officer/admin boundary instance instead proves the boundary positively (the officer clears RBAC and is stopped by `ERR_PACKET_STATE_INVALID` 409, never 403).

Orchestrator verification: all three files parse as valid YAML; top-level keys correct (`scaffold_difficulty_design` / `scaffold_corner_design` singletons); confirmed neither design key leaked into SCAFFOLD.yaml.

## Step 4: Generate PRD — 2026-09-01T00:15:00.000Z

Subagent summary (verbatim):

PRD generation is complete and verified.

**Output**: `workspace/PRD.md` — 540 lines, ~15,600 words, 111 KB. Non-truncated: starts at the H1 title, ends on the final §5 error row (`ERR_NON_POSITIVE_NET_STIPEND` | 422), which is the last entry in the scaffold's error catalogue.

**Structure**: 5 top-level sections, 22 subsections.
- §1 Introduction (evidence-file pain point, scope, two design commitments)
- §2 Global Specifications, 11 subsections: 2.1 identity/roles, 2.2 response structure (copied verbatim from `section-2.2-response-structure.md`, byte-identical), 2.3 pagination/filters, 2.4 identity & versioning, 2.5 logical clock, 2.6 stale-parent guards, 2.7 the full 54-step refusal precedence ladder, 2.8 cascade ordering, 2.9 separation of duties, 2.10 rounding/money, 2.11 window geometry
- §3 Business Logic, 9 subsections: 3.1 sites/cohorts/enrolment, 3.2 mentor certification cycles, 3.3 matching, 3.4 contact hours, 3.5 observation cycles (two status dimensions), 3.6 seminars/attendance, 3.7 readiness/milestones/licence, 3.8 stipends, 3.9 state completion packets
- §4 endpoint table: exactly 4 columns, 59 rows (all scaffold endpoints incl. `POST /_clock/set_current_utc`)
- §5 error table: exactly 2 columns, 70 rows

**Hard Contract 1 — Field-Name Coverage: PASS.** Machine-checked against the scaffold: 144/144 `entities[].fields[].name`, 82/82 endpoint `input` fields plus the 3 OCC fields, 12/12 computed-read output object keys, 47/47 state-machine values, 70/70 error ids, 5/5 roles — all present in backticks, zero missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 54 validations appear as the numbered precedence ladder in §2.7, each with error id and HTTP status (verified line-by-line against `priority`; the only three non-literal matches are the multi-error families at priorities 5, 6 and 40, all of which enumerate every member id). All 12 state machines / 64 transitions are described with preconditions, error ids and side effects (Mentor 8, Cohort 3, NoviceTeacher program_status 8, NoviceTeacher license_advancement_status 5, MentorMatch 6, ContactLog 5, ObservationCycle phase 6, ObservationCycle feedback 6, MilestoneAttainment 5, SeminarSession 2, StipendDisbursement 4, CompletionCertification 6). All 9 calculations are reconstructible operand-for-operand, including both variants of the stipend rule (per-log rounding before summation), both variants of the readiness index (live vs. frozen snapshot, with the fixed denominator evaluation order), and the base-score-keyed tier lookup of the completion score. All 3 concurrency rules are in §2.6. No pseudocode, no operator syntax, no fuzzy quantifiers.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,090 backtick tokens scanned between `## 3.` and `## 4.`; zero begin with `/`, zero are a bare HTTP method, zero combine method+path.

**Scaffold tensions resolved** (each in favour of the more detailed / self-consistent source, the state machines):
- Packet `RETURN` moves `program_status` back to `ACTIVE` (state machine + the `REOPEN` and `WITHDRAW`-from-`RETURNED` transitions all agree); the endpoint's one-line side-effect saying the novice stays `COMPLETION_PENDING` was not followed.
- Packet `WITHDRAW` documented from both `ASSEMBLING` and `RETURNED`, with the program_status nuance on each path.
- `NoviceTeacher` `ACTIVE -> MATCHED`/`ACTIVE -> ENROLLED` on match-end is included (declared in the endpoint side effects, absent from the state-machine transition list).
- Cohort region-scoping and the two submission gates that carry no declared error id (`seminar_sessions_required`, all gating milestones `ATTAINED`) are stated as requirements without inventing error codes.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

Orchestrator verification: PRD.md is 540 lines / 111841 bytes, opens on the H1 and closes on the final error-table row. Independent cross-check against SCAFFOLD.yaml confirms 70/70 error ids, 59/59 endpoint paths, and 162/162 entity field names present in the PRD.

## Step 6: Generate implementation — 2026-09-01T02:00:00.000Z

First attempt (launched concurrently with Step 5) died to the same stream watchdog as Step 2's first attempt — "no progress for 600s", zero files written, stalled mid-Read of PRD.md (540 lines / 111KB, ~207 chars per line). Relaunched with a hard cap of 60-line Read slices on PRD.md, 200-line slices on SCAFFOLD.yaml and the skill spec, 250-line cap on Writes, and a mandate to split across multiple modules. Retry succeeded.

Subagent summary (verbatim):

Implementation complete and verified.

## Deliverable
`workspace/implementation/`

| file | lines | contents |
|---|---|---|
| app.py | 61 | `create_app()`, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers, `0.0.0.0:$PORT` |
| errors.py | 105 | all 70 error ids -> HTTP status + default messages |
| store.py | 162 | in-memory dicts (13 collections), logical clock, id/version/`created_at` minting, per-request touch set |
| envelope.py | 89 | `meta`/`response_type`/`data` envelope, `req_`+20-alnum ids, pagination rung |
| auth.py | 194 | ladder rungs 1-4 (role header, role recognized, identity resolution, RBAC, ownership/scoping) |
| validators.py | 200 | FK rung 6, typed-field rung 7 helpers, list filters |
| calc.py | 202 | 9 calculations (contact weights, tier rates, adjacency, window geometry, readiness, completion score) |
| domain.py | 308 | cross-entity queries, derived counters, provisional accrual, readiness snapshot, license gate |
| cascades.py | 244 | deterministic + 2 conditional cascades, lapse sweep, lock/unlock, packet re-scoring |
| routes_config.py | 209 | sites, cohorts, milestones, `POST /_clock/set_current_utc` |
| routes_mentors.py | 180 | registration, training credits, 5-action certification machine |
| routes_novices.py | 160 | enrolment, readiness, withdraw, retention outcome |
| routes_matching.py | 235 | auto-selection ranking, propose, ACTIVATE/REJECT/SUSPEND/RESUME/END |
| routes_contact_logs.py | 228 | create, review (VERIFY/DISPUTE/REJECT), resubmit, void |
| routes_observations.py | 266 | cycles, phase advance, feedback, feedback-review |
| routes_seminars.py | 207 | sessions, HELD/CANCELLED, attendance + credit ratio |
| routes_attainments.py | 154 | create, ATTAIN/REVOKE/REOPEN |
| routes_stipends.py | 169 | draft, supersede, APPROVED/PAID/CLAWED_BACK |
| routes_packets.py | 202 | create, SUBMIT/REOPEN/WITHDRAW, state ACCEPT/RETURN |
| start.sh / requirements.txt | 12 / 1 | `$PORT`-aware foreground launcher, `flask>=2.2` |

**3588 lines total, 19 .py modules** — every file complete, no truncation, no Write over 250 lines.

## Coverage
- **13 entities**, all in-memory dicts keyed by UUID; **zero seeding** — no file I/O anywhere (`grep` for `open(`, `sqlite3`, `json.dump`, `pickle`, `/tmp/` returns nothing).
- **59 endpoints** across the ten blueprints, `strict_slashes=False`.
- **12 state machines**, including both parallel dimensions: NoviceTeacher (`program_status` x `license_advancement_status`) and ObservationCycle (`phase` x `feedback_review_status`).
- **54 validations** wired as §2.7's numbered ladder, first-violated-wins: auth/role/identity (1-4) -> ownership (5) -> FK (6) -> field shape (7) -> state gates -> SoD (22) -> domain rules (23-52) -> pagination last. Notable orderings implemented exactly: observation window conflict (24) before invalid window (27); stipend stale-version (21) before window/period/duplicate; attainment state -> SoD -> prerequisite -> requirements -> revocation limit.
- **70 error ids** with PRD status codes; **3 OCC rules** -> 412 `ERR_STALE_PARENT_VERSION`; **5 roles** with segregation-of-duties on all 4 guarded operations.
- **9 calculations** with `Decimal`/`ROUND_HALF_UP`, integer cents, `ROUND_DOWN` for weighted minutes, 180-min daily cap, 240-min ISO-week cohort cap, 0.45/0.30/0.25 readiness weights against the 85.00 gate, 4dp seminar credit ratio at 0.75, completion score with retention-bonus tiers.
- PRD chosen over SCAFFOLD at 4 conflict points (state ACCEPT -> `license_stage = CLEAR`; withdrawal cascades only ASSEMBLING+RETURNED packets; SUBMIT gate `evidence_milestone_count >= 3` and `base_score >= 75.00`; review VERIFY/DISPUTE<-SUBMITTED, REJECT<-DISPUTED), plus §3.2's certification table over rule 17's garbled summary.

## Boot test
`python3 -m py_compile` passes on all 19 modules. Three live `PORT=<free> bash start.sh` runs exercised ~60 curl calls: envelope/meta shape, pagination and auth/identity/ownership precedence, POST creates for site/mentor/cohort/novice/match/log/cycle/session/attainment/stipend/packet, auto-match tier ranking, caseload exhaustion -> `ERR_NO_ELIGIBLE_MENTOR`, 180-min cap -> `ERR_DAILY_CREDIT_CAP_REACHED`, dispute->resubmit, void->revocation cascade, mentor SUSPEND/REINSTATE match cascade, a 2028 clock jump triggering the lapse sweep, site/cohort closure refusals, and withdrawal decrementing `enrolled_novice_count`. Final run: `ALL DONE`, `exit=0`, `0` tracebacks in the server log.

Orchestrator verification: 19 .py modules + start.sh + requirements.txt, 3588 lines; `python3 -m py_compile` clean on all; grep for `sqlite3|json.dump|shelve|pickle|/tmp|open(` returns nothing (pure in-memory confirmed); start.sh honours `$PORT`, binds 0.0.0.0, execs in foreground. Independent boot on port 18733 confirms all 7 probed list collections return `[]` at boot — zero seeded data — with a well-formed `meta`/`response_type`/`data` envelope.

## Step 5: Generate unit tests — 2026-09-01T02:10:00.000Z

Subagent summary (verbatim):

Suite complete. Final two files emitted and the whole suite audited.

## Files

`test_helpers/` (7 modules + `__init__.py`, 1,870 lines): `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (`conftest.py` + 20 test modules, 8,198 lines):
- Queue A: `test_101_dual_variant_calculations.py`, `test_102_contact_credit_combinatorics.py`, `test_103_completion_bonus_tier.py`, `test_104_bounded_loops_and_parallel_dimensions.py`, `test_105_transitive_cascades.py`, `test_106_precedence_pairs.py`, `test_107_boundary_precision.py`, `test_108_cross_entity_state_gates.py`, `test_109_temporal_resources.py`, `test_110_compensating_invariants.py`
- Queue B: `test_201_entities.py`, `test_202_state_machines.py`, `test_203_calculations.py`, `test_204_validations.py`, `test_205_endpoints.py`, `test_206_errors.py`, `test_207_errors.py`, `test_208_rbac.py`, `test_209_cross_cutting.py`, `test_210_consistency.py`

## Counts

- **109 test functions, 124 collected tests** (15 extra from two parametrized groups in `test_206_errors.py`).
- Every test function has **exactly one** well-formed `Design:` line as the final docstring line (programmatic AST audit: 0 problems).

## Coverage audit (mechanical, against both yaml indices)

| | instances | translated | bad tags | uncovered |
|---|---|---|---|---|
| Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`) | 20 non-stub | 20 | 0 | 0 |
| Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`) | 68 non-stub (+17 stubs) | 68 | 0 | 0 |

**100% of non-stub instances translated. Zero PRD-first-filter skips** — every instance survived the two-condition filter. The 17 queue-B `excluded_because` stubs are all de-duplication pointers back to a named §1.8 instance, so nothing was lost by leaving them alone.

## Verification

- `python3 -m py_compile` on all 29 emitted files: clean.
- `pytest --collect-only`: 124 tests, no collection errors (proves imports/fixtures resolve).
- Citation checker (literal grep of every quoted PRD span): **ALL CITATIONS VERBATIM** across all 20 test modules.
- `pyflakes`: one finding only — the intentional `# noqa: F401` side-effect import in `test_suite/conftest.py:15` that registers the error->HTTP-status map.
- No file mentions "scaffold"; all identifier/AST-level import names resolve against the real helper modules.

## Adjudications made in the last file pair

`test_209_cross_cutting.py` (3 OCC instances) — the recipe for `occ_match_creation_rejects_mentor_version_stale_by_one_match` asserted `active_caseload_count == 1` then `== 2` after PROPOSED proposals; PRD line 235 defines that counter over `ACTIVE` matches only, so both asserts became `0`. `occ_stipend_draft_...` had its `period_code` normalized to the quarter form `2026-Q3` and its non-PRD `verified_minutes` assert dropped.

`test_210_consistency.py` (1 instance) — clock advanced to `2026-08-05T12:00:00Z` before the `2026-08-03` contact date (the recipe would otherwise file a future-dated log). Asserts the 120-minute verify response *itself* carries `credited_minutes 120` / `stipend_cents 8400` / `EXACT` / `1.00`, then the void response itself carries the zeroed unwind, with the four-hop reconciliation checked on match, mentor, novice and readiness in both directions.

That closes out all six recipe-versus-PRD conflicts adjudicated across the run (RETIRE-with-PROPOSED-match, the 270-minute seminar masked by the weekly-cap rung, quarter-form period codes, the July window overlapping the verification instant, the ambiguous 33-character narrative, and the caseload counter) — each resolved in favour of the PRD, with no instance weakened, skipped or stubbed.

Orchestrator verification: test_helpers/ + test_suite/ total 10068 lines; `py_compile` clean on all files; `pytest --collect-only` yields 124 tests with no collection errors. Independent AST audit confirms 109 test functions each carrying exactly one well-formed `Design:` line as the final docstring line (0 problems), zero tags referencing non-existent instances, and 88 unique design instances covered = 20 queue-A + 68 queue-B (several instances legitimately spawn more than one test function).

## Step 7: Run tests and iterate — 2026-09-01T02:35:00.000Z

Subagent summary (verbatim):

Clean: in-memory dicts only, no seeding, no disk persistence.

## Summary

**Iterations run: 2** (each an 8-round parallel stability sweep). Final sweep: **124/124 passed in all 8 rounds**, 0 failed, 0 errors, 0 skipped.

**Iteration 1 findings** — 10 tests failed identically in all 8 rounds (no flakiness anywhere in the suite; per-round results were byte-for-byte consistent, so no timing-sensitive bugs surfaced).

**Tests deleted: none.** Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so all 10 resolved as either a test mis-translation (STEP 2) or an implementation bug (STEP 3).

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — `attainment_for()`: previously raised `AssertionError: no attainment row for milestone X` whenever the test defined a milestone *after* the novice was enrolled. Enrolment only seeds rows for milestones "currently in the catalogue" (§3.7), so the PRD-faithful path for a later milestone is the explicit `POST /milestone-attainments` endpoint ("Explicit creation exists only for milestones introduced after a cohort is already under way"). The helper now falls back to that endpoint. This one fixture bug was the upstream cause of 4 independent-looking failures.

**Fixes applied to `test_suite/`** (assertion mis-translations; none weakened — each was made stricter/more specific)
- `test_202_state_machines.py::TestContactLogTerminalGuards` — asserted `stipend_accrued_cents == 0` after a refused void of a **SUBMITTED** log. §3.8 states the provisional accrual's "input set is the mentor's contact logs whose `verification_status` is `SUBMITTED` or `VERIFIED`", priced from projected minutes. Corrected to the PRD-derived 4200 cents (60 min, `EXACT` tier, 1.00 multiplier).
- `test_206_errors.py::TestUniquenessFamily` — asserted `credited_seminar_sessions == 1` against a session never marked `HELD`. §3.6 is explicit: a credited row on a still-`SCHEDULED` session "only lifts the novice's `credited_seminar_sessions` once the session is marked held". Corrected to 0.
- `test_208_rbac.py::TestSharedEvidenceCreation` — booked the site lead's observation window at `2026-08-06T09:00-10:00` while the logical clock stood at `2026-08-05T12:00`, then expected the `OBSERVED` advance to succeed; §3.5 requires "the logical clock to have reached or passed `window_end`", so the implementation correctly returned 409. Rebooked the window to `2026-08-05T11:00-12:00`, which both closes before the clock and clears the 30-minute same-mentor travel buffer against the mentor's 10:00 end.

**Fixes applied to `implementation/`**
- `store.py` (`NOT_FOUND_ERRORS`) + `errors.py` (status map) — three 404 identifiers were spelled outside the §5 closed catalogue: `ERR_SESSION_NOT_FOUND` -> `ERR_SEMINAR_SESSION_NOT_FOUND`, `ERR_ATTENDANCE_NOT_FOUND` -> `ERR_SEMINAR_ATTENDANCE_NOT_FOUND`, `ERR_PACKET_NOT_FOUND` -> `ERR_CERTIFICATION_NOT_FOUND` (the names §2.7 rung 5 and the §5 table both mandate).
- `cascades.py::revoke_unsupported_attainments()` — hop two of the contact-log void cascade set rows to `REVOKED` but never touched `attained_milestone_count`, because the route refreshes the novice's counters *before* the cascade runs and only re-derives the snapshot afterward. §3.7 requires a revocation to decrement `attained_milestone_count` on every path; the decrement now happens per revoked row.

Orchestrator verification: independently parsed all 8 `results.{1..8}.json` — every round reports passed=124 total=124 failed=0 errors=0 skipped=0. Grep confirms zero `pytest.mark.skip`/`xfail` anywhere in test_suite/ or test_helpers/; `pytest --collect-only` still yields 124 tests, corroborating the zero-deletions claim; implementation remains pure in-memory (no sqlite/json.dump/pickle//tmp/open()).

## Step 9: Complete PRD — 2026-09-01T03:15:00.000Z

Subagent summary (verbatim):

**Deliverable:** `workspace/PRD_COMPLETED.md`

**Size:** `PRD_FINALIZED.md` 540 lines / 112,285 chars -> `PRD_COMPLETED.md` 540 lines / 126,328 chars (**char-delta +14,043**, line-delta **0**). All 70 diff hunks are in-place `NcN` line replacements — no added/deleted lines, no new sections, no new paragraphs.

**Counts:** 70 changes = **31 ambiguity-pins** + **39 mismatch-revisions**.

Per-change bullets (`{PRD section} — {insert|revise} — {kind} — {what changed} — {impl ref}`):

- §2.1 Authentication — insert — ambiguity — opaque-identity roles must also present a non-blank `X-User-ID`, refused 401 `ERR_UNAUTHENTICATED` ahead of any role check — `auth.py:47`
- §2.2 Envelope — insert — ambiguity — `api_request_id` = `req_` + exactly 20 uppercase-alnum chars, regenerated per response — `envelope.py:14`
- §2.2 Envelope — insert — ambiguity — `api_request_timestamp` is the logical clock, never wall clock — `envelope.py:22`
- §2.2 Envelope — revise — mismatch — `response_type: "error"` envelope also wraps 5xx (`ERR_INTERNAL`, 500) — `app.py:41-51`
- §2.3 Pagination — insert — ambiguity — empty/non-integer/negative `limit`/`offset` -> `ERR_INVALID_PAGINATION` (400) — `envelope.py:77`
- §2.3 Filtering — insert — ambiguity — filters are exact string equality except list-membership, boolean tokens and date-prefix matches; unparseable filter values yield an empty page, never a refusal; list reads are silently identity-scoped instead of refused — `validators.py:166`, `auth.py:141`
- §2.4 Representations — insert — ambiguity — responses carry every declared field including explicit nulls; underscore-prefixed ordering keys are never emitted — `store.py:147`
- §2.5 Clock — revise — mismatch — clock hook enforces no role and no identity, echoes a single field, and accepts backwards (non-monotonic) settings, running the lapse sweep afterwards — `routes_config.py:203-209`
- §2.7 rung 2 — insert — ambiguity — opaque-role identity resolution sits between authentication and the role check — `auth.py:47`
- §2.7 rung 8 — insert — ambiguity — ownership applies only to rows carrying an anchor; cohorts, seminar sessions and milestones are exempt — `routes_config.py:117`
- §2.7 rung 10 — revise — mismatch — match-`ACTIVE` gate applies to contact-log creation/verification and forward phase advances, not to abandonment or dispute/reject — `routes_contact_logs.py:44`, `routes_observations.py:142`
- §2.7 rung 12 — revise — mismatch — feedback review consults cycle `phase` only on `ACCEPT`; `RETURN` never reads it — `routes_observations.py:251`
- §2.7 rung 16 — revise — mismatch — packet withdrawal is legal from `ASSEMBLING` or `RETURNED` — `routes_packets.py:109`
- §2.7 rung 17 — revise — mismatch — certification source states pinned: `CERTIFY` from `UNCERTIFIED`, `RECERTIFY` from `LAPSED` only — `routes_mentors.py:132`
- §2.7 rung 18 — revise — mismatch — novice withdrawal admits `ENROLLED`/`MATCHED` as well; packet `ACCEPT` re-checks `COMPLETION_PENDING` — `routes_novices.py:18`, `routes_packets.py:176`
- §2.7 rung 23 — revise — mismatch — the certification rung has two arms: expiry is consulted only for match `ACTIVATE`/`RESUME`; elsewhere only `certification_status` — `routes_matching.py:205`, `routes_contact_logs.py:44`
- §3.1 Sites — insert — ambiguity — closure `reason` bounded 1-1000 chars; re-closing a `CLOSED` site -> `ERR_SITE_CLOSED` — `routes_config.py:69`
- §3.1 Cohorts — insert — ambiguity — `target_status` enum is `RUNNING|CLOSED`; `RUNNING` is always refused `ERR_COHORT_STATE_INVALID`, and `CLOSED` is reachable from `FORMING` or `RUNNING` — `routes_config.py:123-140`
- §3.1 Enrollment — insert — ambiguity — the cohort's enrolled counter is recomputed and its version bumped on every enrollment — `routes_novices.py:141`
- §3.1 Retention — revise — mismatch — outcome enum includes `LEFT_PROFESSION` and `UNKNOWN`, `observed_on` is required, and no program-status gate applies — `routes_novices.py:152`
- §3.2 Training credits — revise — mismatch — `SiteInductionLead` may post credits, `hours` is unbounded, `completed_on` is only format-validated — `routes_mentors.py:83-88`
- §3.2 Certification — insert — ambiguity — `reason` is required only for `SUSPEND` — `routes_mentors.py:129`
- §3.2 Certification — insert — ambiguity — `REINSTATE` past expiry or with no expiry -> `ERR_MENTOR_CERT_STATE_INVALID`; expiry is never extended — `routes_mentors.py:146`
- §3.2 Certification — insert — ambiguity — `RETIRE` with a `PROPOSED`/`ACTIVE` match -> `ERR_MATCH_STATE_INVALID`, checked before the cert-state arm — `routes_mentors.py:142`
- §3.3 Matching — insert — ambiguity — `reason` required only for `REJECT`/`END`; `SUSPEND` requires `ACTIVE` — `routes_matching.py:166-182`
- §3.3 Matching — insert — ambiguity — `RESUME` re-runs the capacity gates, admits novice `MATCHED` or `ACTIVE`, and does not restamp `activated_at` — `routes_matching.py:205`
- §3.4 Contact logs — revise — mismatch — creation reads mentor `certification_status` only, never expiry — `routes_contact_logs.py:44`
- §3.4 Contact logs — insert — ambiguity — creation bumps the mentor's version only (novice and match untouched) — `routes_contact_logs.py:78`
- §3.4 Contact logs — insert — ambiguity — decision enum `VERIFY|DISPUTE|REJECT` with source states `SUBMITTED|SUBMITTED|DISPUTED`; `note` required for `DISPUTE`/`REJECT` — `routes_contact_logs.py:120`
- §3.4 Contact logs — insert — ambiguity — `VERIFY` clears `dispute_reason` — `routes_contact_logs.py:143`
- §3.4 Contact logs — revise — mismatch — `DISPUTE` touches log and mentor; dispute/reject do not require an `ACTIVE` match — `routes_contact_logs.py:160`
- §3.4 Void — insert — ambiguity — a disbursement in `APPROVED`/`PAID` blocks the void with `ERR_DISBURSEMENT_STATE_INVALID` — `routes_contact_logs.py:209`
- §3.4 Void cascade — revise — mismatch — hop four nulls `decided_at`/`decided_by_user_id` and reverts the novice from `COMPLETION_PENDING` to `ACTIVE` — `cascades.py:187-194`
- §3.5 Cycles — revise — mismatch — creation check order pinned; mentor gate is `certification_status` only — `routes_observations.py:40`
- §3.5 Phases — insert — ambiguity — `to_phase` enum excludes `PRE_CONFERENCE`; `reason` optional and unstored; premature `OBSERVED` -> `ERR_OBSERVATION_PHASE_INVALID` — `routes_observations.py:131`
- §3.5 Phases — insert — ambiguity — `ABANDONED` needs no `ACTIVE` match — `routes_observations.py:142`
- §3.5 Feedback — revise — mismatch — only the narrative ceiling is enforced, repeated saves are tolerated, rubric keys are a subset check, and composite fields reset on redraft — `routes_observations.py:194`
- §3.5 Feedback — revise — mismatch — draft is reachable from `NONE`/`DRAFT`/`RETURNED` with phase `OBSERVED` or `POST_CONFERENCE` — `routes_observations.py:211`
- §3.5 Review — revise — mismatch — `ACCEPT` checks phase before feedback state; `RETURN` ignores phase entirely — `routes_observations.py:251`
- §3.6 Seminars — revise — mismatch — cohort-state refusal id and check order pinned; the cohort version is bumped only on the `FORMING`->`RUNNING` promotion — `routes_seminars.py:122-128`
- §3.6 Seminars — insert — ambiguity — cancellation consults neither the clock nor cohort state — `routes_seminars.py:112-135`
- §3.7 Attainments — insert — ambiguity — explicit creation requires novice `ACTIVE`; the duplicate check ignores the existing row's status — `routes_attainments.py:33`
- §3.7 Attainments — revise — mismatch — one decision endpoint serves all three decisions, open to `ProgramAdmin` or `SiteInductionLead` — `routes_attainments.py:86`
- §3.7 Attainments — insert — ambiguity — attestation clears `revoked_on`/`revoke_reason` and overwrites `evidence_note` only when supplied — `routes_attainments.py:117`
- §3.7 Attainments — revise — mismatch — revoke `reason` is optional; `REOPEN` clears the revocation fields and touches no novice counter — `routes_attainments.py:92,149-153`
- §3.7 Readiness — insert — ambiguity — components reported at 4 dp; the read persists `readiness_index_live`/`_snapshot` without bumping the novice version — `routes_novices.py:96`
- §3.8 Stipends — insert — ambiguity — `period_end <= period_start` -> `ERR_INVALID_WINDOW`, evaluated before `ERR_PERIOD_NOT_CLOSED` — `routes_stipends.py:51`
- §3.8 Stipends — insert — ambiguity — `adjustment_cents` defaults to 0 and is bounded +/-500000, out-of-range -> `ERR_INVALID_REQUEST` — `routes_stipends.py:46`
- §3.9 Packets — revise — mismatch — creation admits novice `ACTIVE` or `COMPLETION_PENDING`, state checked before the version compare, novice version always bumped — `routes_packets.py:32`
- §3.9 Packets — insert — ambiguity — `reason` required only for `WITHDRAW`; the submit-time rescore is provisional (not persisted); the three evidence gates all raise `ERR_MILESTONE_EVIDENCE_INSUFFICIENT` — `routes_packets.py:103-123`
- §3.9 Packets — insert — ambiguity — `ACCEPT` re-checks novice `COMPLETION_PENDING`/`RECOMMENDED` after packet state and SoD, then ends `ACTIVE`/`SUSPENDED` matches with `PROGRAM_COMPLETED` — `routes_packets.py:176`
- §4 role table — revise — mismatch — dropped the spurious `StateCredentialingOfficer` cell (15 separate rows: sites, cohorts, mentors, matching, contact logs, observation, seminar, attainment, stipend and packet operations) — `@guard` lists across the route modules
- §4 role table — revise — mismatch — added the missing `SiteInductionLead` cell for the mentor training-credit row — `routes_mentors.py:83`
- §4 role table — revise — mismatch — corrected the `POST /cohorts/{id}/close` description (explicit `target_status`, `RUNNING` refused) — `routes_config.py:123-140`
- §4 role table — revise — mismatch — clock hook row marked as accepting any role and requiring no identity — `routes_config.py:203`
- §5 Error catalogue — insert — ambiguity — framework-level ids outside the catalogue: `ERR_NOT_FOUND` (404, unrouted paths and 405s) and `ERR_INTERNAL` (500); malformed JSON bodies surface as `ERR_INVALID_REQUEST` — `app.py:38-51`

Notes on judgment calls: `ERR_VALIDATION` exists in `implementation/errors.py:20` but is never raised anywhere in the codebase, so it was deliberately left undocumented rather than inventing behavior. All 70 catalogued error ids were programmatically diffed against `errors.ERROR_STATUS` — every id/status pair already matched, so no status corrections were needed.

Orchestrator verification: PRD_COMPLETED.md is 540 lines / 126,328 chars (PRD.md 111,841 -> PRD_FINALIZED.md 112,285 -> PRD_COMPLETED.md 126,328). Every diff hunk against PRD_FINALIZED.md is an in-place replacement with identical line ranges on both sides — zero whole-line insertions or deletions; heading count steady at 28 across all three PRD variants, confirming no new sections. Post-Step-9 confirmation run of the full suite (per-test-server isolation): 124/124 passed, 0 failed, 0 errors, 0 skipped in 152.5s — Step 9 is doc-only and left the passing state intact.

## Pipeline complete — 2026-09-01T03:20:00.000Z

All steps 1-9 finished. Final artifact inventory verified on disk: SCAFFOLD.yaml (3299), SCAFFOLD_DIFFICULTY_DESIGN.yaml (2097), SCAFFOLD_CORNER_DESIGN.yaml (4367), workspace/INSTRUCTION.md (53), workspace/PRD.md (540), workspace/PRD_FINALIZED.md (540), workspace/PRD_COMPLETED.md (540), test_helpers/ + test_suite/ (10068 lines, 124 tests), workspace/implementation/ (19 modules, 3588 lines) with results.{1..8}.json all green at 124/124.

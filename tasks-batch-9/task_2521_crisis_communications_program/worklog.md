# Worklog — task_2521_crisis_communications_program

## Step 1: Create task directory — 2026-09-03T05:12:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program` and its `workspace/` subdirectory. Index 2521 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T07:01:00.000Z

Done. All three artifacts are complete and the linter is clean.

## Verification

```
§1.5 endpoints declared:    59
§1.1 entities declared:     12
§1.8 instances scanned:     26
§1.9 instances scanned:     75   (real recipes; plus 45 excluded_because stubs = 120)
Calls scanned (§1.8+§1.9):  1426

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

`wc -l`: SCAFFOLD.yaml 2841 · SCAFFOLD_DIFFICULTY_DESIGN.yaml 2788 · SCAFFOLD_CORNER_DESIGN.yaml 5875 (all in `/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/`). `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key. All 146 instance names are globally unique, every stub cites an existing §1.8 instance name, every claim_type is a row from `references/claim-extraction-guide.md`, and all 51 catalogued error ids are triggered somewhere in §1.8/§1.9.

## Domain model (§1.0–§1.7)

`domain_name: crisis-communications-program`, `api_prefix: /crisis`, flat topology, parallel state-machine shape, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers.

- **12 entities**: TeamMember, MonitoredChannel, Incident, IssueSignal, TeamAssignment, Statement, ApprovalTask, StakeholderNotice, PreparedMaterial, MediaInterview, MisinformationClaim, PostCrisisReview.
- **11 state machines** (Incident carries two parallel dimensions: `response_state` MONITORING→ACTIVATED→RESOLVED and `privilege_state` NON_PRIVILEGED→PRIVILEGED_ASSERTED→PRIVILEGE_WAIVED, with `comms_posture` OPEN/RESTRICTED/FROZEN as a third derived gate); Statement is cyclic (DRAFT↔IN_REVIEW↔REVISION_REQUESTED, capped at 3 rounds) and MisinformationClaim forks TRIAGED→{PLATFORM_ESCALATED, CORRECTION_ISSUED}→CLOSED.
- **59 endpoints**, 10 calculations, 33 validations (priority-ordered 1–20+), 51 errors, 7 roles (ProgramAdmin opaque; IncidentLead, LegalCounsel, CommsLead, Spokesperson, SocialListener, ExecSponsor entity-backed), 2 §1.2.1 concurrency rules (`statement-create-stale-incident`, `correction-issue-stale-channel`), 3 conserved ledgers (open_approval_task_count, reserved_correction_minutes, scheduled_interview_minutes).

## §1.8 — 26 instances across all 9 rules

dual_variant_calc 2 · combinatorial_formula 3 (modes a/b/c) · non_linear_state_machine 3 · transitive_cascade 4 (incl. depth-4 resolve cascade) · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 3 · resource_temporal_overlap 2 · compensating_invariant 3.

## §1.9 — 120 instances / 9 sections

entities 11 · state_machines 15 (9+6 stubs) · calculations 20 (10+10) · validations 18 (12+6) · endpoints 15 (9+6) · errors 24 (14+10) · rbac 5 · cross_cutting_complexity_layers 10 (3+7) · consistency_model 2.

## Design adjudications

- **59 endpoints deliberately exceeds the Expert 20–32 band** ("harder than expert level"); entity count was trimmed 15→12 to keep the surface coherent, and `/crisis` is a pure namespace over flat collections (no nested URLs).
- **Reachability fix in §1.5/§1.3**: the approval-routing eligibility filter no longer excludes the drafter. With the old filter, `ERR_SEGREGATION_OF_DUTIES` (priority 14) was unreachable — an empty pool always surfaced as `ERR_APPROVER_UNAVAILABLE` first. New clause (e) documents that the drafter stays in the pool and the conflict surfaces on `decide`. No existing §1.8/§1.9 recipe was affected (verified programmatically: no recipe has a drafter holding an approver seat).
- **`ERR_STATEMENT_NOT_IN_REVIEW` reachability**: its only reachable window is the privilege cascade, which voids *only* uncleared assignees — so a cleared counsel keeps a PENDING task whose statement is already REVISION_REQUESTED. That is now an explicit §1.9 errors instance, including the claim that priority 10 answers before the FROZEN posture at priority 12.
- **Constant reconciliation**: added `AUDIENCE_SEQUENCE_RANK` and `REGULATORY_OVERRIDE_WINDOW_MINUTES: 120` to `calculations.stakeholder_reach_index.constants` (the notice-release statutory override referenced an undeclared constant).
- **Role-table reconciliation**: `POST /crisis/stakeholder-notices/{notice_id}/release` moved from `CommsLead.exclusive_operations` into both CommsLead's and LegalCounsel's `shared_operations` to match §1.5; all 59 endpoints were then cross-checked §1.5↔§1.7 in both directions.
- **Grounds repairs**: `state_machines.Incident_privilege.*` → `state_machines.Incident.privilege_state.*` (3 refs) and `state_machines.MonitoredChannel.UNVERIFIED_to_VERIFIED` → `entities.MonitoredChannel.fields.escalation_path_state` (there is no channel state machine).
- **§1.8/§1.9 overlap policy**: numeric snapshots are reused where they must agree (exposure_factor 0.0101, SEV1/2/3 chains 96.00/83.00/63.00) and configurations are deliberately varied where they must not collide (max_concurrent_corrections 2 vs 1; embargo equality vs review-deadline equality; virality 59/60 vs the verification gate; priority pair 31/32 vs §1.8's three pairs).
- Noted but not "fixed": validation 19's per-incident role uniqueness makes the routing AUTHORITY_RANK/created_at tie-break unreachable, so §1.9's routing claims target eligibility filtering and the atomic empty-pool failure instead of ranking.

## Step 3: Copy Shared Files — 2026-09-03T07:01:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:12:00.000Z

Orchestrator truncation check: `wc -l` = 418 lines / 93153 bytes; `tail` ends at the final row of the §5 error table (`| ERR_CHANNEL_CORRECTION_CAPACITY | 409 |`) — a real section boundary, not mid-sentence. All five top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue) are present with 26 subsections. No regeneration needed.

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/workspace/PRD.md` (418 lines), built incrementally via one Write plus four `cat >>` heredoc appends plus the table generator. The file ends cleanly at the final row of the §5 error table.

## Section structure

- **§1 Introduction** — 3 paragraphs (pain-point angle → system scope → two design commitments: posture-as-gate, auditable-by-arithmetic).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC & identity, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Flat Topology / Path Resolution / Collection Filters, 2.6 The Communications Posture Gate, 2.7 Precision, Rounding and the Three Conserved Ledgers, 2.8 Optimistic Concurrency on Shared Parents, 2.9 Order of Rejection (all 33 priorities), 2.10 Privilege Circle / Decision Authority / Segregation of Duties.
- **§3 Business Logic** — 9 subsections organised as a crisis timeline: 3.1 standing readiness (roster/channels/dark site), 3.2 issue monitoring and escalation score, 3.3 activation, severity and the holding-statement clock, 3.4 privilege as an independent dimension, 3.5 message development / quorum routing / revision loop, 3.6 publication, withdrawal and stakeholder sequencing, 3.7 spokesperson designation and interview prep, 3.8 misinformation and the correction fork, 3.9 resolution and post-crisis assessment.
- **§4** 59-row endpoint table (4 columns). **§5** 51-row error table (2 columns).

## Coverage

- **Endpoints:** 59/59 in the §4 table; every action endpoint additionally narrated in §3 via state-transition/role-verb/capability framing.
- **Entities:** 12/12; all 125 distinct field names present verbatim in backticks.
- **Calculations:** 10/10 translated to precise prose with pinned evaluation order preserved (signal escalation score's round-before-sum, containment score's band keyed on the pre-fee base incl. the 52.50→55.13 case, reach index's round-per-notice-then-sum incl. the 3.03-vs-3.02 case, both severity variants, both reputation-delta variants, readiness decay's 16-day/17-day boundary, quorum + routing, ledger recomputation).
- **Validations:** 33/33, each numbered in §2.9 with its error ID and status, and each trigger condition restated in the §3 workflow it guards.
- **Errors:** 51/51 in §5; all 51 also referenced in §2 or §3 narrative.
- **Transitions:** 39/39 including the three declared invalid-from rejections and all system-event cascades (escalate 4-hop, privilege-assert 3-hop, revision-requested 4-hop, resolve 3-hop).
- **Concurrency rules:** 2/2 with `write_endpoint` + `expected_incident_version`/`expected_channel_version` + exact error ID and 412 status, framed purely as stale-version rejection.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- state values: 100% present; enum-field values: 100% present; role names: 7/7
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose (ordered list, §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 59 checked, 59 expressed, 0 missing
- entities[].fields[] structured content: 125 checked, 125 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked (claim close PLATFORM vs CORRECTION, interview cancel from CONFIRMED vs SCHEDULED, statement withdraw from IN_REVIEW vs PUBLISHED, severity provisional vs final, reputation delta raw vs adjusted), 5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 853
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two notes for the record. First, §2.2 was diffed byte-for-byte against `skills/prd-bench-doc-generator/section-2.2-response-structure.md` — exact match. Second, the scaffold has two internal inconsistencies I resolved by stating the **union** so no fair implementation is penalised: `ERR_STATEMENT_STATE_INVALID`'s condition omits `PUBLISHED` as a withdraw from-state while the transition table declares `PUBLISHED → WITHDRAWN` (PRD admits DRAFT, IN_REVIEW, REVISION_REQUESTED, APPROVED and PUBLISHED), and `escalate-platform`'s endpoint side-effects set `resolution_branch` while the entity and state machine say it stays null until close (PRD says the branch is settled at the fork but `resolution_branch` is written at close). Neither design file was opened.

## Step 5: Generate Unit Tests — 2026-09-03T08:09:00.000Z

(Orchestrator note: Steps 5 and 6 were launched as two background Agent calls seconds apart rather than in one message. Isolation was preserved regardless — a directory check at 07:23Z, while the impl generator was still writing its first modules, showed `test_suite/` did not yet exist, and the impl generator was additionally given an explicit hard prohibition on reading `test_suite/` or `test_helpers/`. The test generator's summary below opens with the words "Step 7 is complete"; that is the subagent mislabelling its own step number — the artifacts it reports are the Step 5 test suite and helpers, and it is pasted verbatim as the skill requires.)

Step 7 is complete. Both output directories are on disk, every file parses, the suite collects, and every test is traceable to exactly one design instance.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/test_helpers/` — 2855 lines total: `__init__.py` 47, `api_client.py` 402 (59 endpoint methods), `api_errors.py` 145, `assertions.py` 218, `constants.py` 149, `factories.py` 397, `fixtures.py` 954, `test_users.py` 77, `types.py` 466.

`/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/test_suite/` — 7259 lines, 127 tests: `conftest.py` 17; queue B — `test_01_registry_records.py` 464, `test_02_state_machines.py` 540, `test_03_role_access.py` 466, `test_04_endpoint_behaviour.py` 507, `test_05_validation_gates.py` 698, `test_06_error_catalogue.py` 690, `test_07_derived_calculations.py` 525, `test_08_concurrency_and_consistency.py` 415; queue A — `test_09_severity_and_reputation_variants.py` 268, `test_10_score_matrices.py` 265, `test_11_boundary_precision.py` 300, `test_12_validation_priority.py` 296, `test_13_cross_entity_gates.py` 348, `test_14_lifecycle_paths.py` 383, `test_15_resource_overlap.py` 275, `test_16_conserved_ledgers.py` 311, `test_17_cascades.py` 491.

## Coverage

- **Queue A (difficulty): 26/26 instances, exactly 2 tests each = 52 tests.** All nine rules complete, including the four `transitive_cascade` instances finished last (reject→void→block→restrict; resolve→stand-down→cancel→release minutes; escalate→retier→retroactive deadline→breach; privilege→void uncleared approver→reopen revision).
- **Queue B (corner): 74/75 non-stub instances, 75 tests.** None of the 45 `excluded_because:` stubs was translated.
- Verified mechanically: 127 test functions, every docstring ends with exactly one `Design:` line, every tag resolves to a real non-stub instance, no dual tags, no untagged tests, no stub tagged. `pytest --collect-only` reports 127 collected; all `test_*/*.py` pass `ast.parse` and `pyflakes` (only the expected re-export notices from the `test_helpers/__init__.py` facade). No generated file mentions the scaffold or the design docs.

## Skipped instances

1. **`Corner/errors/corner_error_statement_not_in_review_after_privilege_reopened_revision`** — fails condition 2 (unique derivability). `ERR_STATEMENT_NOT_IN_REVIEW` is unreachable by this route: either the task has already left `PENDING`, in which case §2.9 check 10 answers `ERR_APPROVAL_TASK_NOT_PENDING` first, or the statement is still `IN_REVIEW` and the incident is under legal hold, in which case check 12 answers `ERR_COMMS_POSTURE_FROZEN` first. The PRD never yields a state in which the asserted error is the first failure.

No other instance was dropped, but four design recipes had to be retargeted (PRD governs; the tested behaviour is preserved):

- **SEV3/SEV4 activated incidents and `quorum_required == 1` are unreachable.** Activation demands an `ESCALATED` signal (§3.3), escalation demands `escalation_score >= 70.00` (§3.2), and the provisional reading bands the largest score over `LINKED`+`ESCALATED` — so an activated incident is always SEV2 or SEV1 and the quorum is always 2 or 3. Recipes premised on "SEV3 activated, signal scoring 63.00" (including the privilege-cascade one) were retargeted to SEV2; `test_helpers.setup_activated_incident` asserts this outright.
- The privilege cascade therefore runs at quorum 2 with counsel approving first, and the design's `approvals_recorded == 0` assertion was dropped — it is 1, the surviving in-circle approval.
- Invalid `scenario_code` literals (`SERVICE_OUTAGE`, `REGULATORY_ACTION`, ...) were replaced with members of the PRD's five-code playbook; `corrected_claim_count` assertions on an *incident* were dropped (it is a PostCrisisReview field).
- Timestamp assertions use `startswith(...)` rather than equality, because the PRD pins three fractional digits only for `created_at`/`updated_at`.

The suite was written blind to `workspace/implementation/` and no sibling task directory was read.

## Step 6: Generate Implementation — 2026-09-03T08:09:00.000Z

Implementation is complete and verified end-to-end.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `core.py` | 516 | error catalogue (all 51 ids -> HTTP status), `ApiError`/`fail`, Decimal helpers (`round2`/`round4`/`floor_minutes`/`floor_days`), logical clock + in-memory `Store` (12 dicts, `_seq` tie-break), envelope builders (`ok`/`ok_list`/`error_response`), `authenticate`, `Field`/`validate_body`, pagination + filter helpers |
| `logic.py` | 549 | pinned constants and enums, all 10 calculations, the 3 conserved-ledger recomputations + derived counters, `recompute_posture`, gate helpers, shared cascades, 12 FK resolvers |
| `routes_registry.py` | 242 | clock + TeamMember + MonitoredChannel + PreparedMaterial (12 endpoints) |
| `routes_incident.py` | 394 | incident CRUD, activate, assert/waive privilege, resolve, sla-sweep (8) |
| `routes_team.py` | 268 | team-assignments + issue-signals (9) |
| `routes_statement.py` | 392 | statements + approval-tasks (10) |
| `routes_notice.py` | 174 | stakeholder-notices (5) |
| `routes_interview.py` | 198 | media-interviews (5) |
| `routes_claim.py` | 337 | misinformation-claims + post-crisis-reviews (10) |
| `app.py` | 72 | blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` |
| `start.sh` | 12 | `set -euo pipefail`, guarded flask install, `exec python3 app.py` (chmod +x) |
| `requirements.txt` | 1 | `flask>=2.2` |

3155 lines total. Every `.py` file passes `python -m py_compile`. Storage is pure in-memory dicts; nothing is seeded, no file/DB/tmp persistence; a fresh process starts with 12 empty collections and the clock at `2026-08-01T00:00:00Z`.

## Endpoint coverage
`app.url_map` enumerates **exactly 59** method+path pairs, matching the PRD §4 table one-for-one (1 clock + 4 team-member/... registry groups + incident lifecycle + signals + statements/approval-tasks + notices + interviews + claims + reviews). No extra or missing routes.

## Validation ordering
Every handler is written as a straight-line sequence in PRD §2.9 numeric order, one guard per step, first failure wins: `authenticate()` covers steps 1-3 (headers -> role -> identity resolution), `validate_body()` covers step 4 (unknown field, type, enum, range, string length) plus endpoint-specific step-4 interval checks, then path/body FK resolution (5-6), ownership (7), OCC (8-9), from-state (10), incident ACTIVATED (11), `require_not_frozen`/`require_open_posture` (12), privilege circle (13), segregation of duties (14), seat/quorum/pool checks (15-18), deadline/embargo (20-21), calendar buffer (22), escalation prerequisites (24), revision budget (25), audience sequence (26), training (27), question pack (28), escalation-path/virality (29-30), capacity (33). Where §3 prose disagreed with §2.9 the numeric order won (documented in inline comments) — verified live: on a FROZEN incident a stale `expected_incident_version` yields 412 (step 8) while a fresh version yields `ERR_COMMS_POSTURE_FROZEN` 409 (step 12).

## Conserved ledgers and OCC
All three ledgers are recomputed from scratch by scanning children (never incremented/decremented): `Incident.open_approval_task_count` (PENDING tasks of live statements), `MonitoredChannel.reserved_correction_minutes` (sum of `correction_window_minutes` over `CORRECTION_ISSUED` claims), `TeamMember.scheduled_interview_minutes` (CONFIRMED interviews). `refresh()` runs after every mutation of an incident or any of its children and also recomputes `comms_posture` under the three-rule precedence. Smoke run confirmed conservation: 0 -> 3 -> 0 approval tasks, 0 -> 45 -> 0 reserved channel minutes across the correction issue/close cycle, 0 -> 45 speaker minutes on confirm. `TeamMember`/`MonitoredChannel` versions bump only when a recomputed counter actually changes.

OCC is exactly two rules and no other endpoint accepts a version field: `expected_incident_version` on `POST /crisis/statements` -> `ERR_STALE_INCIDENT_VERSION` 412, and `expected_channel_version` on issue-correction -> `ERR_STALE_CHANNEL_VERSION` 412; both were exercised and both returned 412 with the observed-vs-actual version in the message.

## Boot + smoke results
Booted from a fresh process via `PORT=<random> bash start.sh` (server answers in <5s) and drove 97 requests: zero 500s, zero tracebacks in the server log. Exercised registration of 6 members / 2 channels / 1 material, channel escalation-path verification, incident open -> 5 seats + acknowledgements -> signal create/escalate -> activate -> holding statement draft/submit-review/quorum decide/publish -> notice queue/release -> interview schedule/confirm -> both claim forks (platform + correction) -> sla-sweep -> assert/waive privilege -> resolve -> retrospective scoring, plus error paths (401 missing headers, 404 unresolvable `X-User-ID`, 404 unknown path id, 400 unknown body field / bad `limit` / bad enum filter, 403 wrong role and 403 non-assignee decide, 409 duplicate seat role / notice sequence / double booking / FROZEN posture, 412 both OCC rules, 422 question pack and virality thresholds, 405 wrong method).

Arithmetic spot-checks all matched hand computation: `escalation_score` 100.00 (90x1.00 + 15 REGULATORY - 15 sentiment + 12 reg flag, capped), SEV1 at score 100.00, `holding_statement_due_at` = activation + 30 min, `base_containment_score` 70.00 -> MEDIUM band 0.10 -> `containment_priority_score` 77.00, `approval_latency_minutes` 10, reach contributions 50.00 (EMPLOYEE x1.00) + 40.00 (MEDIA x2.00) = index 90.00, readiness 100.00 -> 57.50/STALE after 17 whole days via the sweep, `exposure_factor` 0.5000, `reputation_delta_raw` -7.50 and `reputation_delta_adjusted` -2.50 (-7.50x(1-0.5)+2.50x0.5) with `reported_delta` mirrored onto the incident.

Envelopes match PRD §2.2 exactly: `meta.api_request_id` is `req_` + 20 chars, `api_request_timestamp` is wall-clock UTC with 3 fractional digits and `Z`, list responses add `limit`/`offset`/`total_count`/`has_more`, `response_type` is `object`/`array`/`error`, and error `data` carries only `error_id` + `message` with error `meta` carrying only the two request fields. My smoke server was killed at the end (two later `python3 app.py` processes in that directory belong to a concurrent agent and were left alone); `__pycache__` removed so the deliverable is only the 12 source artifacts.

## Step 7: Run Tests and Iterate — 2026-09-03T08:31:00.000Z

(Orchestrator verification, per the known "false clean sweep" failure mode: I independently read all 8 `workspace/implementation/results.*.json` files myself — every one reports `passed == total == 127`. `grep -c Terminated workspace/sweep.log` = 0, so no round was reaped. The sweep was run under `setsid nohup` as instructed.)

All 8 rounds green: **127/127 passed, 0 failed, 0 errors, 0 skipped** in every round (results.1–8.json, ~285 s each, no `Terminated` in `workspace/sweep.log`).

## Summary

**Iterations run:** 2 full 8-round sweeps (iteration 1: 112/127 in all 8 rounds, 15-test union, perfectly deterministic — no load-induced flakiness; iteration 2: all green).

**Tests deleted:** none. Every failure traced to a defect in `test_helpers/`, one assertion mis-translation in `test_suite/`, or one implementation divergence — no test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_helpers/`**
- `/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/test_helpers/api_errors.py` — `ApiErrorId` enum: all 51 members renamed from `X` to `ERR_X` so the member name equals the PRD §5 error id verbatim (values unchanged). All 13 `ApiErrorId....` references in `test_suite/` use the `ERR_`-prefixed form (0 use the unprefixed form), so every one of them raised `AttributeError: type object 'ApiErrorId' has no attribute 'ERR_...'` before reaching the HTTP call. This single fixture fix accounted for 13 of the 15 failures (test_11 x2, test_12 x6, test_13 x3, test_15 x2).

**Fixes applied to `test_suite/`**
- `test_08_concurrency_and_consistency.py::test_incident_version_advances_only_on_writes` — `assert_state(swept, "ACTIVATED", "incident")` -> `assert_field(swept, "response_state", "ACTIVATED", "incident")`. `assert_state` reads `entity["state"]`, but an Incident has no `state` field: PRD §3.3 names the dimension `response_state` ("`response_state` tracks the response itself, running `MONITORING -> ACTIVATED -> RESOLVED`"), which is what every other incident-state assertion in the suite uses. The fix makes the assertion more faithful, not weaker (it was the only `assert_state(..., "incident")` call in the suite).

**Fixes applied to `implementation/`**
- `workspace/implementation/routes_incident.py`, `sla_sweep()` — removed the `break` that expired only the first overdue `PENDING` task per `IN_REVIEW` statement, leaving its siblings `VOIDED` by the revision cascade. PRD §3.3 states the checkpoint "expires approval tasks that have outrun their review deadline" (plural, qualified per task), and §3.5's trigger is stated per task ("while a `PENDING` task's statement is `IN_REVIEW` and the current instant is strictly past `review_deadline_at`, the task advances `PENDING -> EXPIRED`"). Since every task of a round shares the statement's single `review_deadline_at`, all of them satisfy the trigger; the one-task reading also has no PRD tie-break for choosing which task, so the all-tasks reading is the only determinate one. `push_revision_requested` still runs afterwards (its sibling-voiding pass now finds nothing pending), and `open_approval_task_count` still recomputes to 0.

No endpoints, response fields, side effects or seeded data were added; storage remains in-memory dicts only.

## Step 8: Finalize PRD — 2026-09-03T08:39:00.000Z

(Orchestrator note: Step 8 was NOT skipped — Step 7 applied one `implementation/` fix plus test-layer fixes, so the skip condition, which requires zero fixes of every kind, did not hold.)

`/home/ubuntu/github/CodingPRD/tasks/task_2521_crisis_communications_program/workspace/PRD_FINALIZED.md` is written.

## Line counts
- PRD.md: 418 lines; PRD_FINALIZED.md: 418 lines (+0 lines, 0.0% delta) — one line revised in place, no insertions/deletions.

## Changes
- §3.5 (Silence-is-rejection paragraph, line 236) — revise — pinned the checkpoint's expiry as all-tasks-per-round: every `PENDING` task of the `IN_REVIEW` statement's current `revision_round` advances `PENDING -> EXPIRED` in creation order (not just the first overdue one), and the subsequent `REVISION_REQUESTED` push finds no `PENDING` sibling left, so a task the checkpoint reached ends `EXPIRED` rather than `VOIDED` — `implementation/routes_incident.py:364-381` (loop over `L.round_tasks(statement)` setting `state = "EXPIRED"`, then `L.push_revision_requested`).

## Items requiring no PRD change
- `test_helpers/api_errors.py` `ApiErrorId` `ERR_`-prefix rename: pure fixture-naming bug; PRD §5 already lists every error id verbatim with the `ERR_` prefix, and impl emits exactly those strings. No PRD silence.
- `test_suite/test_08 ... assert_state -> assert_field("response_state")`: pure test mis-translation. PRD §3.3/§3.4 already name the incident's response dimension `response_state`, §2.5 lists `response_state` (not `state`) as the incident filter, and impl stores `incident["response_state"]` with no `state` key anywhere. Nothing under-determined.

## Pre-edit search log
Edit 1 — §3.5 checkpoint expiry
- (a) Subject: how a `PENDING` approval task leaves `PENDING` without a decision — specifically the `EXPIRED` vs `VOIDED` outcome and the per-round scoping of any sweep/cascade pass over a statement's tasks.
- (b) Impl paths enumerated (read or grepped): `routes_incident.py:355-396` `sla_sweep` (Step 7 site; the only writer of `"EXPIRED"` in the whole impl, verified by `grep -rn EXPIRED`); `logic.py:479-485` `push_revision_requested` (voids remaining round tasks, blocks queued notices, recomputes `approvals_recorded`); `logic.py:453-460` `void_pending_round_tasks` (the sole `VOIDED` writer, honours `exclude_task_id`); `logic.py:117-122` `round_tasks` (scoping is the statement's *current* `revision_round`); `routes_statement.py:385-391` reject branch (`push_revision_requested(..., exclude_task_id=task["id"])` — siblings here genuinely end `VOIDED`); `routes_statement.py:282-285` withdraw-from-`IN_REVIEW` (`VOIDED`); `routes_incident.py:208-229` privilege-assertion cascade (voids outside-circle `PENDING` tasks, then pushes only when `remaining` is empty and `approved < quorum_required`); `logic.py:463-476` `block_queued_notices` / `unblock_notices`; `routes_statement.py:51` `TASK_STATES` (confirms `EXPIRED` and `VOIDED` are distinct observable states).
- (c) Wording adjustments made: (i) scoped the "nothing left to void / ends `EXPIRED` rather than `VOIDED`" clause strictly to the checkpoint sentence, so the rejection, withdrawal and privilege-assertion paths that do still produce `VOIDED` tasks are not contradicted — the paragraph's following sentence ("tasks reach `VOIDED` in three other ways ...") is kept verbatim and remains true; (ii) said "that statement's current `revision_round`" rather than "all of the statement's tasks", matching `round_tasks`' round filter so prior-round rows are not implicated; (iii) phrased the plural expiry as a consequence of the round sharing one `review_deadline_at` rather than as a new sweep-only rule, keeping it consistent with §3.5's per-task trigger and §3.3's already-plural "expires approval tasks"; (iv) added "in creation order" only (matching the `_seq` sort) and deliberately avoided asserting anything about which statements the sweep visits or about `open_approval_task_count`/notice effects, which the existing prose and §3.3 already cover for both the sweep and the rejection path.

## Step 9: Complete PRD — 2026-09-03T09:05:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **three sequential, file-partitioned passes** over `implementation/` rather than as one subagent. A single-agent Step 9 on a 10-module / 59-endpoint implementation has repeatedly returned a `PRD_COMPLETED.md` that is byte-identical to its input — i.e. the scan never actually ran. Partitioning bounds each pass's reading load and makes a no-op pass detectable. Partition: **A** = `core.py` + `app.py` + `logic.py`; **B** = `routes_registry.py` + `routes_incident.py` + `routes_team.py`; **C** = `routes_statement.py` + `routes_notice.py` + `routes_interview.py` + `routes_claim.py`. Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; B and C edited it in place with the Edit tool (never Write, to avoid clobbering prior passes). Every pass was required to report `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` and justify a zero.

Orchestrator verification: `wc -l` = 418 for all three PRD variants (no truncation); `wc -c` 93568 -> 110354 (**+16786 chars**); `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = **178**; `grep -c '^## '` = 5 (all five top-level sections present); tail ends at the final §5 error-table row; grep for `scaffold` / `difficulty_design` / `corner_design` / `test_recipe` / `harder than expert` across both `PRD.md` and `PRD_COMPLETED.md` returns nothing — no design-index or difficulty-instruction leakage.

Aggregate totals across the three passes: **45 ambiguity-pins, 7 mismatch-revisions**, 0 new sections, line count unchanged at 418 (all edits are in-paragraph).

### Pass A — core.py / app.py / logic.py (diff 0 -> 70 lines; 14 ambiguity-pins, 3 mismatch-revisions)

- §2.1 — insert — ambiguity — header values are stripped before inspection/resolution, so a whitespace-only header counts as empty and `X-User-ID` resolves in trimmed form — core.py:306-308
- §2.2 (`api_request_id`) — insert — ambiguity — pinned as `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — core.py:233-237
- §2.2 (`api_request_timestamp`) — insert — ambiguity — it is the one instant read from real wall-clock time, not the logical clock — core.py:240-242
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` (`10.5`, empty, non-numeric) is equally `ERR_INVALID_REQUEST` — core.py:462,469
- §2.3 — insert — ambiguity — `created_at` ties (common under a static logical clock) break by creation order, making list ordering total and stable — core.py:226,513
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, never wall clock — core.py:207-222
- §2.4 — insert — ambiguity — a `TeamMember`'s `updated_at`/`version` move only when a derived counter actually changes — logic.py:363-369
- §2.5 — insert — ambiguity — unknown *query* params ignored; `privilege_cleared` accepts `true/false/1/0` any case; `revision_round` must be an integer; identifier filters are unvalidated exact matches yielding an empty page — core.py:477-509
- §2.6 — insert — ambiguity — defines `blocked_notice_count` as notices in `BLOCKED` (PRD used it undefined) — logic.py:379
- §2.7 — insert — ambiguity — decimals are serialised as plain JSON numbers, so `100.00` goes out as `100.0` — core.py:245-247
- §2.9 step 4 — insert — ambiguity — absent body = `{}`; non-object body = 400; explicit `null` = omission; datetime leniency (`Z`, offsets converted, naive read as UTC); strings untrimmed and whitespace-only fails non-empty; ints refuse bools/fractions; two-decimal number fields round half up at ingest rather than rejecting — core.py:339-449
- §2.9 step 11 — **revise** — **mismatch** — an `ACTIVATED`-requiring operation on a `RESOLVED` incident answers `ERR_INCIDENT_ALREADY_RESOLVED`, not `ERR_INCIDENT_NOT_ACTIVATED` (all 9 call sites verified) — logic.py:410-414
- §3.1 — insert — ambiguity — the 0.00 floor is the only clamp; a backward clock reposition drives the day count negative and the readiness score above 100.00 — logic.py:275-282
- §3.5 (routing) — insert — ambiguity — a `created_at` tie among candidate seats breaks by seat creation order — logic.py:309-311
- §3.5 (approval) — **revise** — **mismatch** — dropped the "on the incident" qualifier: the block/unblock cascades key on the notice's `statement_id` alone, while `blocked_notice_count` keys on `incident_id` — logic.py:463-476 vs 379
- §3.5 (rejection) — insert — ambiguity — `approvals_recorded` is recomputed as the round's `APPROVED` count, so pre-rejection approvals keep counting and it is not zeroed until revision — logic.py:485-491
- §3.6 / §3.7 — insert — ambiguity — defines `released_notice_count` and `confirmed_interview_count` (both previously undefined) — logic.py:380,384
- §5 intro — **revise** — **mismatch** — the catalogue claimed to list *every* identifier; noted the three transport-level ones impl can emit: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — app.py:44-62

Verified-as-already-pinned (no change): the full 52-entry error->status map matches §5 row-for-row; all 10 calculation formulas, their pinned pre-rounding and evaluation order, both severity candidate sets and tier bands, all SLA/review window tables, all weights/rates/caps/thresholds and enum vocabularies match PRD text exactly; the 3 conserved-ledger definitions and `active_assignment_count`/`open_escalation_count` match §2.7/§3.1 verbatim; `recompute_posture` matches §2.6's three-rule precedence; the 13 FK resolvers map to the 13 declared 404 identifiers; auth rejection order matches §2.9 steps 1-3.

### Pass B — routes_registry.py / routes_incident.py / routes_team.py (diff 70 -> 118 lines, 48 of them its own; 15 ambiguity-pins, 1 mismatch-revision)

- §2.9 step 6 — insert — ambiguity — pinned body-FK resolution order (`incident_id` -> `channel_id` -> member ref -> statement ref) so a doubly-unresolvable payload reports the earlier one — routes_team.py:55-56,161-162
- §2.9 step 11 — **revise** — **mismatch** — PRD said "privilege changes" require not-`RESOLVED`; impl's waive-privilege carries no such check. Narrowed to privilege *assertion* plus seat acknowledgement, calling out waiver as exempt — routes_incident.py:236-247
- §3.1 ¶roster — insert — ambiguity — `media_training_expires_at` is optional and defaults to null even for `CURRENT`; a value supplied with `NONE` is discarded, not rejected — routes_registry.py:71-73
- §3.1 ¶channel-verify — insert — ambiguity — no from-state: re-verifying an already-`VERIFIED` channel is accepted, overwrites the reference and bumps `version` again — routes_registry.py:167-171
- §3.1 ¶material-review — insert — ambiguity — `reviewer_notes` is a mandatory non-empty string — routes_registry.py:233
- §3.1 ¶decay — insert — ambiguity — a re-score landing on the same score+state leaves the material's `version` untouched — routes_incident.py:389-392
- §3.2 ¶signal-inputs — insert — ambiguity — `sentiment_score` is the one score field *not* quantised to 2dp on ingest; penalty computed from the unrounded value — routes_team.py:152 vs routes_claim.py:72
- §3.2 ¶signal-create — insert — ambiguity — creation-time linking tests neither `response_state` nor `comms_posture`, and recomputes the incident's counters/posture without incrementing its `version` — routes_team.py:158-188
- §3.2 ¶escalation — insert — ambiguity — posture is the only response-dimension gate, so a `RESOLVED` incident answers `ERR_COMMS_POSTURE_FROZEN` not `ERR_INCIDENT_ALREADY_RESOLVED`; posture precedes the threshold test — routes_team.py:243-253
- §3.2 ¶escalation — insert — ambiguity — escalation always bumps the incident `version`, including on a still-`MONITORING` incident where severity/deadline/containment stay null — routes_team.py:258-267
- §3.3 ¶seating — insert — ambiguity — acknowledgement never moves the member's `version`; neither seating nor acknowledgement touches the incident's counters or `version`; posture gate applies to acknowledgement — routes_team.py:83,130-137
- §3.3 ¶activation — insert — ambiguity — `MONITORING` is the only from-state; an already-`ACTIVATED` incident also answers `ERR_INCIDENT_ALREADY_RESOLVED`; guards run in §2.9 order (seat check 15 before signal check 24, `SEV1` counsel last) — routes_incident.py:143-166
- §3.3 ¶sla-sweep — insert — ambiguity — sweep declares no from-state and is never refused on the response dimension; version bump still happens on a no-op — routes_incident.py:354-396
- §3.4 ¶assert — insert — ambiguity — an out-of-state assertion is refused with `ERR_COMMS_POSTURE_FROZEN`, even when the posture is `OPEN`; resolved case tested first — routes_incident.py:191-195
- §3.4 ¶waive — insert — ambiguity — `waiver_reason` mandatory but not persisted; out-of-state waiver also `ERR_COMMS_POSTURE_FROZEN`; no resolved check; no `LEGAL_COUNSEL` seat check; `privilege_basis` retained — routes_incident.py:239-249
- §3.4 ¶waive — insert — ambiguity — the waiver restores nothing the assertion destroyed (voided tasks, `REVISION_REQUESTED` statements, `BLOCKED` notices) — routes_incident.py:250
- §3.9 ¶resolve-gates — insert — ambiguity — resolution is **not** posture-gated: an incident under a legal hold may be resolved without waiving privilege, and `privilege_state` is untouched — routes_incident.py:274-282
- §3.9 ¶cascade — insert — ambiguity — the two member-side recomputations run together once per affected member over the union of stood-down members and cancelled-booking spokespeople, so `version` advances by exactly 1, not 2 — routes_incident.py:335-345

### Pass C — routes_statement.py / routes_notice.py / routes_interview.py / routes_claim.py (diff 118 -> 178 lines, 60 of them its own; 16 ambiguity-pins, 3 mismatch-revisions)

- **§2.6** — revise — mismatch — `FROZEN` exemptions corrected from "exactly three" to four: recording an approval decision has no posture test and no response-dimension test at all, so a privilege-cleared assignee can still decide on a legal-hold incident — routes_statement.py:338-392 (reachable because routes_incident.py:215 spares cleared assignees' `PENDING` tasks while :205 freezes the posture)
- **§3.6 release guards** — revise — mismatch — "guarded by five conditions" -> six, adding the `ACTIVATED` requirement (`ERR_INCIDENT_NOT_ACTIVATED`) that §2.9 step 11 already assigns to notice release — routes_notice.py:119
- **§3.6 statutory override** — revise — mismatch — `priority_override_used` records *use*, not eligibility: true only when at least one lower-ranked notice really was unsettled; all four conditions met with nothing unsettled records false. Also pinned `priority_override` as the payload's one field, optional, default false — routes_notice.py:112,153
- §3.5 submit-review — revise — ambiguity — "revision budget exhausted" means exactly `revision_locked` true (not the `revision_round >= 3` form used at revise), and per §2.9 it loses to `ERR_APPROVER_UNAVAILABLE` — routes_statement.py:168-177
- §3.5 decide guards — insert — ambiguity — the six listed conditions are the complete guard set, evaluated in §2.9 order not the listed order; omitted `decision_comment` stored as null — routes_statement.py:341-371
- §3.5 approval — insert — ambiguity — an approval never increments the incident's `version` (unlike a rejection), while the statement's `version` increments on every approval even below quorum — routes_statement.py:383-384
- §3.5 revision — revise x2 (same paragraph) — ambiguity — `body` is the only field, mandatory, same at-most-4000 non-empty rule as at creation; `approvals_recorded` lands at 0, `submitted_at`/`review_deadline_at` are left standing, statement `version` +1 but incident's untouched — routes_statement.py:211,224-228
- §3.6 withdrawal — revise — ambiguity — "In both paths" -> every path: withdrawal from `DRAFT`/`REVISION_REQUESTED`/`APPROVED` also increments the incident's `version` — routes_statement.py:302-303
- §3.6 notice queuing — insert — ambiguity — the named statement may be in any state and need not belong to the notice's own `incident_id`; queuing leaves the incident's `version` untouched — routes_notice.py:58-78
- §3.7 booking — insert — ambiguity — booking leaves both the incident's and the spokesperson's `version` untouched — routes_interview.py:104
- §3.7 cancellation — insert + revise (same paragraph) — ambiguity — no ownership binding: any `Spokesperson` caller may cancel any booking; the `SCHEDULED` branch leaves incident and member `version` untouched — routes_interview.py:178,195-197
- §3.8 claim logging — insert — ambiguity — the `open_claim_count` recompute is not a mutation, so the incident's `version` is untouched and the containment family is not re-scored until triage — routes_claim.py:98
- §3.8 platform branch — insert — ambiguity — incident side untouched: `open_claim_count` unmoved, containment not re-scored, incident `version` does not advance — routes_claim.py:165-167
- §3.8 correction intro — revise — ambiguity — the stale-version check precedes the *from-state* check too, so a stale version on a `DETECTED` claim answers `ERR_STALE_CHANNEL_VERSION` not `ERR_CLAIM_STATE_INVALID` — routes_claim.py:193-201
- §3.8 channel capacity — revise — ambiguity — channel `version` increments unconditionally, even for a sub-minute window flooring to 0 minutes; incident `version` untouched — routes_claim.py:238-242
- §3.9 scoring — revise x2 (same paragraph) — ambiguity — a non-`RESOLVED` incident reuses `ERR_INCIDENT_NOT_ACTIVATED` (409), checked after the review from-state; `playbook_update_count` is mandatory and must be >= 0 — routes_claim.py:311,316-322

Pass C's closing checks: `wc -l` 418 for both files (not truncated); `grep -c '^## '` = 5; `tail -3` ends inside the §5 error table; scaffold-vocabulary grep returned nothing.

Pass C's most significant finding, recorded for downstream review: the §2.6 exemption-count correction is a genuine behavioral mismatch rather than a silence — the shipped implementation lets an approval decision through on a `FROZEN` (and even `RESOLVED`) incident, which the original PRD prose forbade. Per Step 9's contract the implementation is the alignment target, so the PRD was revised to match it rather than the implementation being changed (changing it would also have invalidated the green 8-round sweep).

## Pipeline complete — 2026-09-03T09:05:00.000Z

All nine steps finished. Final state: 3 scaffold artifacts, `workspace/PRD.md` (418 lines) -> `workspace/PRD_FINALIZED.md` -> `workspace/PRD_COMPLETED.md`, 9 `test_helpers/` modules (2855 lines), 18 `test_suite/` files (127 tests), 12-file Python/Flask implementation, and `workspace/implementation/results.{1..8}.json` all reporting 127/127.

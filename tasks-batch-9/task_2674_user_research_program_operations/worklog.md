# Worklog — task_2674_user_research_program_operations

## Step 1: Create task directory — 2026-09-04T04:47:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2674_user_research_program_operations/` and `workspace/` at the pre-assigned path (index fixed by scenario number 2674; no index auto-allocation performed, per orchestration instructions — up to 32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T06:48:00.000Z

All three scaffold artifacts are complete and lint-clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all valid YAML, each ending at a real key boundary):
- `SCAFFOLD.yaml` — 2802 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2716 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5511 lines

SCAFFOLD.yaml (§1.0–§1.7), no design keys present:
- 13 entities (RoadmapDecision, ResearchRequest, ParticipantPool, Participant, Study, Recruitment, ConsentRecord, ResearchArtifact, Theme, Finding, EvidenceLink, Readout, FollowUp), all `common_fields: true`
- 60 endpoints, 51 validation rules (strict priority ladder 1–51), 51 error codes, 8 calculation rules incl. 2 OCC `concurrency_rules`, 5 roles
- complexity profile: `workflow_orchestration` + `compliance_audit`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy`, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`

§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 9 rules × 19 instances (`boundary_precision_check` carries 3).

§1.9 (SCAFFOLD_CORNER_DESIGN.yaml): 92 instances across the guide's nine sections in order — entities 12, state_machines 16, calculations 17, validations 18, endpoints 6, errors 14, rbac 3, cross_cutting_layers 5, consistency_model 1. 56 carry executable `test_recipe`s (1447 calls linted across §1.8+§1.9); 36 are `excluded_because` stubs, every one citing an existing §1.8 instance. All `claim_type` values come from `claim-extraction-guide.md` rows; the `Immutability` row is skipped as inapplicable (no `common_fields: false` entity). All 51 error codes are triggered somewhere across the two design files; instance names are unique across both.

Design adjudications made while writing the remaining sections:
- Priority-shadow avoidance: the pool-OCC corner uses `mode: FORWARD_ESTIMATE` so priority 26 (`ERR_SETTLEMENT_NOT_PERMITTED`) cannot pre-empt priority 30; the study-OCC corner takes the study to GUIDE_APPROVED first so the stale value is a genuine prior version (2) rather than a non-positive 0 that priority 18 would catch.
- `ERR_OWNERSHIP_REQUIRED` is probed with a caller holding an *accepted* role (Stakeholder u_stake_2, then Researcher), proving priority 2 passes and only the identity comparison refuses; both refusals must leave `revision_round` at 0.
- `ERR_UNAUTHENTICATED` (401) vs `ERR_UNAUTHORIZED` (403) separated explicitly, including an undeclared role value `Auditor` → 403, not 401.
- Segregation of duties: the finding is authored by u_lead_1 (itself an accepted publisher role) with strength 0.60 > MIN_PUBLISH_STRENGTH, so priority 47 is satisfied and priority 4 is provably the only refusal; the identical call from u_ops_1 succeeds.
- Role-denial calls were deliberately concentrated in negatively-named instances (`roles_cannot_invoke_other_roles_exclusive_operations`) so the linter's role/payload checks stay active on the positive `shared_operations` instance.

## Step 3: Copy shared files — 2026-09-04T06:48:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T07:06:00.000Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md` — **490 lines** (105,317 bytes), 28 headings, ends cleanly on the final §5 table row (`| ERR_DUPLICATE_LABEL | 409 |`), not mid-sentence.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Counters · 2.5 The Logical Clock · 2.6 The Order in Which Checks Run (full 12-step precedence ladder, all 51 validations) · 2.7 Nested Resource Paths · 2.8 Numeric Precision and Rounding Discipline · 2.9 Stale-Version Rejection on Study and Pool Writes · 2.10 The Incentive Ledger Invariant · 2.11 Derived Postures and Recompute Discipline
- §3 Business Logic & Workflows — 3.1 Decisions to Inform, and the Intake Funnel That Serves Them · 3.2 Panels, Contact Fatigue and the Posture of a Pool · 3.3 Opening a Study, Pinning a Guide, and Getting into the Field · 3.4 Invitations, the Batch Selector, and What an Invitation Costs · 3.5 Screening, Booking a Session, and How Sessions End · 3.6 Consent, Retention, and the Five-Hop Evidence-Withdrawal Cascade · 3.7 The Insight Repository: Themes, Findings and the Evidence Behind Them · 3.8 Readouts, Decision Confidence, and the Follow-Ups That Trail Them · 3.9 Settling the Money, and Measuring the Program
- §4 Endpoint Definitions (60-row, 4-column table)
- §5 Error Code Catalogue (51-row, 2-column table)

**Coverage:** 13 entities · 60 endpoints · 51 validation rules (with priority ordering) · 51 error codes · **13 calculations** · 14 state machines / 57 transitions · 2 concurrency rules · 5 roles.

**Contract 1 — Field coverage check**
```
entities[].fields:        119 required, 119 present, 0 missing
endpoints[].input (req):   58 required,  58 present, 0 missing
endpoints[].input (opt/query): 21 required, 21 present, 0 missing
endpoints[].output keys:   12 required,  12 present, 0 missing
error ids: 51/51 · roles: 5/5 · states: 49/49 · enum values: 83/83
Status: PASS
```

**Contract 2 — Rule coverage check**
```
state transitions:        57 required, 57 documented, 0 missing
calculations:             13 required, 13 documented, 0 missing
validations:              51 required, 51 documented, 0 missing (priority ordering expressed as the §2.6 ladder)
concurrency rules:         2 required,  2 documented (write_endpoint + expected_study_version/expected_pool_version + ERR_STALE_STUDY_VERSION/ERR_STALE_POOL_VERSION + 412)
field defaults/initials:  all documented
cross-entity cascades:    all documented (incl. the five-hop withdrawal cascade)
sibling branches:         all groups at equal density (3 triage outcomes, 3 withdrawal source states, 5 pool postures, 4 participant transitions, 2 settlement modes, 2 strength variants, 2 response outcomes)
Status: PASS
```

**Contract 3 — Path purity check (§3 only)**
```
backtick tokens scanned: 993
tokens starting with `/`: 0
bare HTTP-method tokens: 0
method+path combined tokens: 0
Status: PASS
```

**Notes for the caller**
1. The assignment said "8 calculation rules"; the scaffold actually defines **13**. All 13 are documented.
2. Ten scaffold-internal contradictions were resolved by explicit judgment and documented self-consistently: `priority_score`/`recommended_method` stay null until first triage; fielding leaves `recruitment_status` at `NOT_STARTED` (else `NOT_STARTED → RECRUITMENT_FAILED` is unreachable); withdrawal does not refund `contacts_in_window`; a withdrawn recruitment keeps its `reserved_cents` on the row; recruitment `guide_version_pinned` is copied at invitation and unchanged by (re)scheduling; readout supersession targets other readouts of the same study still in `DRAFT`; `decision_confidence_before` is captured at acceptance; `ERR_DECISION_LOCKED` guards acceptance only; evidence-link deletion is permitted only while the finding is `DRAFT`; zero-budget-pool utilization division was left unspecified because the scaffold is silent (deliberately not invented).
3. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator truncation check:** `tail -25` confirms the file ends at the last error-catalogue row; heading scan shows all of §1–§5 present. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T07:47:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first. Note: due to an orchestrator slip the two Agent calls went out in back-to-back messages rather than one, so Step 6 did not get physical isolation from `test_suite/`. Compensating control: Step 6's prompt carried an ABSOLUTE HARD CONSTRAINT forbidding any read/list/glob/grep of `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`; the returned summary affirms none were ever accessed. PRD-only contract preserved.)

Verification complete and the smoke server is shut down (ports 18674/18675 both free, killed by PID/port only).

## Files emitted — `workspace/implementation/`

| file | lines | role |
|---|---|---|
`start.sh` (exec) | 8 | guarded `pip install` + `exec python3 app.py`
`requirements.txt` | 1 | `Flask==3.0.3`
`app.py` | 63 | `create_app()`, blueprint registration, `ApiError` handler, `0.0.0.0:$PORT` (default 10000), no seeding
`errors.py` | 118 | all 51 error ids + HTTP statuses + default messages
`clock.py` | 55 | logical clock pinned to `2026-08-01T00:00:00Z`, 3-fractional-digit ISO
`store.py` | 82 | 13 in-memory tables, per-request dirty set, one `version` bump per row
`envelope.py` | 114 | `meta`/`response_type`/`data`, pagination (1..100, default 10/0)
`auth.py` | 30 | `X-User-ID`/`X-User-Role`, 5 roles
`validators.py` | 243 | body/query validity + the 13 `*_or_404` resolvers
`serializers.py` | 150 | 13 explicit field projections
`calc.py` | 490 | all 13 calculations
`cascade.py` | 196 | 5-hop evidence-withdrawal cascade + retention sweep (6 counters)
`invites.py` | 53 | reservation/surcharge + invitation side effects
`routes_decisions.py` 183, `routes_pools.py` 189, `routes_studies.py` 280, `routes_recruitments.py` 226, `routes_consent.py` 173, `routes_repository.py` 237, `routes_readouts.py` 234, `routes_ops.py` 25 | | 60 endpoints

Total 3150 lines. `python3 -m py_compile *.py` → clean; `__pycache__` removed.

## Coverage (machine-verified against PRD, not eyeballed)
- **Endpoints: 60/60.** Diffed Flask's `url_map` against the PRD §4 table — zero missing, zero extra.
- **Errors: 51/51**, every HTTP status matches PRD §5 exactly, and every code is actually raised outside `errors.py`.
- **Validations:** the full §2.6 12-step ladder; verified live that step-10 guards beat step-11 OCC (`ERR_SETTLEMENT_NOT_PERMITTED` before `ERR_STALE_POOL_VERSION`) and that a non-`FIELDING` study yields `ERR_RECRUITMENT_CLOSED` before `ERR_PARTICIPANT_SUPPRESSED`.
- **Calculations: 13/13**, spot-checked numerically end to end: surcharge tiers 1000/1000/1050 on a 4000-cent budget then 422; provisional 3.5/4 = 0.88; corroborated 1.0 × 0.6 = 0.60; link contribution 0.85 (OBSERVED_BEHAVIOR × INTERVIEW); theme rollup 0.90 + 0.36 = 1.26 → `ESTABLISHED`; confidence 0.6 × 1.20 = 0.72 → lock clears 0.60; retention horizon `min(180,365,200)` = 180 days; settlement release-then-pay giving paid 1200 / reserved 0 / available 18800 with the §2.10 partition intact; screen-out stipend 200; cascade re-score 2.4/3 × 2/5 = 0.32 → `RETRACTED` → decision unlocked; sweep counters `2/2/2/0/1/0`.

## One real bug found and fixed
`version`/`updated_at` were being **serialized before** the pending bump was committed (`envelope.ok()` committed after the payload was built), so every mutating response returned a stale `version` — an OCC round-trip (`expected_pool_version` echoed straight back from the previous response) failed with `ERR_STALE_POOL_VERSION`. Fixed by flushing in `serializers._dump()` (idempotent `db.commit()`), so representations are always post-mutation. Also removed dead code in `routes_decisions.py` and a stray import in `routes_recruitments.py`, and added `array_response()` so auto-invite's 201 array doesn't emit bogus pagination meta.

## PRD ambiguities resolved by judgment
- **Existence order** follows §2.6's identifier-type order even when a body FK precedes a path segment (participant before study on invite; artifact before finding on evidence-link; decision → study → cited findings on readout draft; request before pool on study create; pool before study on settlement).
- **Ownership/SoD (steps 3-4) precede existence**, but the comparison is skipped when the row is absent so step 5 still yields the 404.
- **Redelivery after deferral:** §3 says deferral "leaves room for a fresh draft readout … delivered again", yet delivery requires `execution_status == ANALYSIS`. I kept the literal precondition (fresh drafts allowed, delivery from `REPORTED` → `ERR_INVALID_STATE`); the state machine declares no `REPORTED → REPORTED` self-loop.
- **Supersede scope** = every other `DRAFT` readout of the same study (PRD over the scaffold's "(study, decision) pair, DRAFT or DELIVERED").
- **`decision_confidence_before`** is null at draft, captured at acceptance; both confidence fields stay null on deferral.
- **`contacts_in_window`** always recounted from recruitment rows (PRD over the scaffold's `+=1/-=1`); withdrawal never refunds contact budget.
- **Cascade hops 4-5** run for every finding whose status *or* `evidence_strength` changed, per §2.11's no-stale-derived-field rule.
- **Theme `reuse_count`** bumps once per theme in the ancestor closure of the cited findings' themes, matching §3.7's "number of ACCEPTED readouts" definition when two cited findings share a lineage.
- **One `version` bump per row per request**, only when the row actually changed; settlement and readout drafting explicitly mark the pool/study so "increments by 1" always holds.
- Invalid enum in a query filter → `ERR_INVALID_REQUEST`; list filters are 404-checked only where the scaffold says so (`GET /findings` checks `study_id`, not `theme_id`).
- `reason` required on withdraw/no-show/revoke, optional on triage/readout response; `guide_question_count` and `actual_duration_min` accept any integer (no declared constraint); a zero-budget pool has utilization 0 → `OPEN`; `POST /studies` against an `IN_STUDY` request → `ERR_INVALID_STATE`, any other non-`APPROVED` → `ERR_METHOD_NOT_APPROVED`; theme depth checked before label uniqueness; a named invitation charges the study's pool but reads the contact window/cap from the participant's own pool; batch-invited rows get `screening_answers` null (screening one scores 0.00 → `SCREENED_OUT`); ordering ties break on insertion sequence because the logical clock stamps rows identically, and null `priority_score` sorts last.

I read only `PRD.md`, `SCAFFOLD.yaml` (entities/endpoints/validations/state_machines) and `INSTRUCTION.md`; `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never listed, read, or grepped.

## Step 5: Generate unit tests — 2026-09-04T07:51:00.000Z

Both stages are complete and all audits are green.

## Files emitted

**`test_helpers/`** — 9 files, 2,916 lines
`constants.py` 174, `api_errors.py` 130 (all 51 PRD error ids + HTTP map registered via `set_error_http_status_map`), `types.py` 431, `test_users.py` 63, `api_client.py` 481 (one method per all 55 endpoints), `factories.py` 295, `assertions.py` 395, `fixtures.py` 915 (six tiers of composite setups), `__init__.py` 32.

**`test_suite/`** — 14 test files + conftest, 10,237 lines
`conftest.py` 51 · `test_01_intake_scoring_and_reframing` 510 · `test_02_study_dimensions_and_fielding_windows` 409 · `test_03_invitation_reservations_and_surcharge` 521 · `test_04_pool_ledger_conservation_and_suppression` 677 · `test_05_session_scheduling_and_consent_gates` 452 · `test_06_evidence_strength_and_link_lifecycle` 794 · `test_07_privacy_cascade_and_readout_delivery` 577 · `test_08_decision_intake_records` 528 · `test_09_readout_settlement_and_metrics` 650 · `test_10_panel_contact_and_invitation_rules` 1249 · `test_11_study_and_guide_state_machine` 665 · `test_12_session_and_consent_workflows` 930 · `test_13_repository_themes_and_findings` 832 · `test_14_platform_conventions_and_access` 1392.

## Tests per queue

140 test functions, 172 collected cases (parametrized families expand). **Queue A: 61 tests over all 19 difficulty instances** (min 2, max 6 — the five-hop consent-revocation cascade got 6, one per hop). **Queue B: 79 tests over all 56 non-stub corner instances** (min 1, max 3). The 36 `excluded_because` stubs were not translated.

## Audits

- **Design-tag pass**: 140/140 tests carry exactly one `Design:` line as the last docstring line; every tag resolves to a real `name:` in the source yaml; zero untagged, dual-tagged, dangling, or stub-pointing tags.
- **Coverage pass**: 19/19 queue A instances at ≥2 tests; 56/56 non-stub queue B instances at ≥1.
- **PRD-citation pass**: 324 quoted spans, all matching `workspace/PRD.md` verbatim after whitespace collapse. I fixed the only 4 failures myself — three in `test_02` had dropped the PRD's `*other*` italic markers, and one in `test_03` had elided a mid-list run with `...`, which I split into two contiguous quotes.
- **Hygiene**: no `skip`/`xfail` markers anywhere; the word "scaffold" appears in neither directory; `py_compile` clean on all 24 `.py` files; pytest collects with no errors.
- **Isolation**: nothing was written under `workspace/` (its only contents are the pre-existing `INSTRUCTION.md`, `PRD.md`, and the concurrently-running implementation agent's `implementation/`); no stray `.md` reports; `__pycache__` swept.

## Instances skipped

**None.** All 19 difficulty and all 56 non-stub corner instances produced tests. What was dropped is individual *assertions* that failed the unique-derivability half of the filter, plus corrections where a design literal contradicted the PRD (PRD wins in every case):

- **Withdrawal** (`pool_cents_conserved_when_invitations_are_withdrawn`): dropped `contacts_in_window == 0` and the recruitment's `reserved_cents == 0` — PRD 3.2 says withdrawal "does not hand contact budget back" and PRD 3.5 says the stored `reserved_cents` "stays on the row as the record of what was released". Money conservation is fully asserted.
- **Guide status at study creation**: asserted `NONE`, not the design's `DRAFT` (PRD 3.3).
- **`guide_status` enum in the version ladder**: the design's `NO_GUIDE`/`GUIDE_APPROVED` replaced with the PRD's `NONE`/`DRAFT`/`APPROVED`.
- **Computed-field names**: `screen_score` and pool `status`, not the design's `screening_score`/`pool_posture`.
- **`recommended_action`**: out-of-enum recipe values replaced with `PROCEED` so the tests reach the rules they claim to test.
- **Fresh draft readout**: `decision_confidence_before` asserted null, not the design's `0.00` (PRD 3.8).
- **Fielding and `recruitment_status`**: asserted `NOT_STARTED`, since PRD 3.3 says fielding "does not touch `recruitment_status`" — this corrected two recipes.
- Also dropped as not uniquely derivable: pool `version` delta after a multi-row settlement walk, entity `version` after a *refused* decision lock, `last_contacted_at` after withdrawal, `screened_in_count` after withdrawal, an `evidence_confidence == 0.60` literal that the canonical setup makes 0.62, and several "no row was created" negatives that no endpoint can observe (replaced with observable equivalents such as the parent-scoped 404 or a positive control).

Two ambiguities worth carrying into the sweep: the incentive-settlement endpoint's success status is asserted as 200 (it is not one of the 13 resource types, so §4's "operations that modify or read an existing resource answer with 200 OK" governs), and `POST /follow-ups/{id}/complete` against a nonexistent id is asserted as `ERR_FOLLOW_UP_NOT_FOUND`, which sits at the §2.6 ownership/existence boundary. I did not run the suite against `workspace/implementation` — the implementation agent is still running and I did not want to contend with its server.

## Step 7: Run tests and iterate — 2026-09-04T08:22:00.000Z

The task is complete. The very first 8-round parallel sweep came back fully clean, and I verified that result rather than taking it at face value.

## Summary

**Iterations run:** 1 (the first 8-round parallel sweep passed; no fix loop was needed).

**Sweep result** — all 8 concurrent rounds, run under `setsid nohup` with `--isolation per-test-server`:

| Round | total | passed | failed | skipped | errors | duration |
|---|---|---|---|---|---|---|
| 1–8 | 172 | 172 | 0 | 0 | 0 | ~309 s each |

The 8 rounds collected an identical 172-test set (verified by symmetric-difference across rounds — empty for all 8), so no round silently skipped or failed to collect anything. No `Terminated` / RemoteDisconnected reaping pattern.

**Tests deleted:** none — there were no failing tests, so the STEP 1 coverage / unique-derivability gate never fired.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Verification I ran because a first-pass clean sweep deserves scrutiny

- **No hidden skips:** zero `pytest.mark.skip`, `xfail`, `skipif`, or `pytest.skip` anywhere in `test_suite/` or `test_helpers/`; runner reports `skipped: 0`.
- **No swallowed assertions:** no `except: pass` / bare `except Exception` in the test artifact.
- **Assertions are real and exact:** 115 `validate_success`, 92 `validate_error` (exact `error_id` checks via the runner's validator), 50 `validate_paginated`, 41 `assert_ledger_partition`, 12 `assert_pool_posture_matches_ledger`. **Zero** `validate_error_is_one_of` relaxations — no exact-error assertion has been downgraded.
- **Implementation contract holds:** no SQLite/file/`/tmp`/pickle persistence, no `json.dump`, no seeding or preloaded entities (`store.py` resets to empty dicts on boot), and no wall-clock reads (`datetime.now`/`utcnow`/`time.time` all absent) — everything reads the logical clock per PRD §2.5.
- **No stray artifacts:** no `test_suite/` or `test_helpers/` leaked under `workspace/`.

### The two generator-flagged ambiguities both check out as PRD-grounded

- **Settlement success = 200.** PRD §4: "Operations that modify or read an existing resource answer with **200 OK**." Settlement mutates the existing pool and creates none of the thirteen declared resource types, so 200 is the uniquely derivable status.
- **`POST /follow-ups/{id}/complete` on a nonexistent id → `ERR_FOLLOW_UP_NOT_FOUND`.** Although §2.6 puts ownership (step 3) ahead of existence (step 5), ownership is unevaluable against a row that does not exist, and step 5 explicitly names "a `FollowUp` named in a path segment, else `ERR_FOLLOW_UP_NOT_FOUND`, on follow-up completion." The 404 is the only coherent reading, so the test is fair.

I also spot-checked the one plausible computed-field-silence candidate: tests assert `contribution` on the evidence-link response. This is PRD-grounded rather than a formula intermediate — §3.7 says each admissible link "**gets a** `contribution`", and §2.8 lists `contribution` alongside `evidence_strength` among the scores subject to the 2-decimal rounding rule, so the field belongs to the link row.

**Orchestrator-side independent verification (memory: a Step 7 subagent can claim a clean sweep while leaving no artifacts behind):** I read all 8 `results.$i.json` myself with a fresh `json.load` — every file reports `passed == total == 172`. Artifacts are present and consistent with the claim.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T08:23:00.000Z

Skip condition met per the skill: Step 7 exited on the **first** 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent spawned; `PRD_FINALIZED.md` is intentionally absent. Step 9 will start from `PRD.md`.

Note that "no Step 7 signal" does not mean "no residual PRD silence" — the implementation generator itself recorded ~15 judgment calls where PRD was under-determined (existence-check ordering, redelivery after deferral, supersede scope, `contacts_in_window` recount, zero-budget pool utilization, tie-breaking on ordering, etc.). Those are exactly Step 9's target class: silences the test suite never asserted against, so they produced no failure signal.

## Step 9: Complete PRD — 2026-09-04T08:50:00.000Z

**Orchestrator decision (recorded per the autonomy instruction):** Step 9 was run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` rather than one monolithic scan. Rationale: `implementation/` is 3,150 lines across 22 modules and `PRD.md` is 105 KB; a single agent asked to walk all of it exhaustively reliably under-covers and can return a file byte-identical to its source (i.e. the scan silently never ran). Partitioning is a coverage measure only — the skill's output contract (one minimal-patch `PRD_COMPLETED.md`, impl as alignment target, no SCAFFOLD/worklog reads, no new sections) was imposed identically on every pass, and passes ran strictly sequentially with explicit "do not revert prior passes / do not re-copy the file" instructions plus handoff notes carried forward.

Partitions:
- **Pass A — platform / cross-cutting**: app.py, errors.py, clock.py, store.py, envelope.py, auth.py, validators.py, serializers.py, routes_ops.py → §2.1–§2.11 + §4 intro.
- **Pass B — intake→sessions**: routes_decisions.py, routes_pools.py, routes_studies.py, routes_recruitments.py, invites.py → §3.1–§3.5 + §3.9 settlement/metrics prose.
- **Pass C — privacy/repository/readouts/math**: routes_consent.py, routes_repository.py, routes_readouts.py, cascade.py, calc.py (all 13 formulas) → §3.6–§3.8 + calculation-bearing §3.9.

### Totals

| | lines | chars |
|---|---|---|
| `PRD.md` (source; Step 8 skipped so there is no `PRD_FINALIZED.md`) | 490 | 105,317 |
| after pass A | 490 | 113,716 |
| after pass B | 490 | 118,827 |
| **`PRD_COMPLETED.md` final** | **490** | **121,855** |

Cumulative delta **+16,538 chars, 0 lines** — every edit is an in-paragraph insert or revision; no new sections, no new paragraphs.

**Counts: 53 edits total — 43 ambiguity-pins, 11 mismatch-revisions** (pass A 14+3, pass B 19+2, pass C 10+6; pass C's two cross-territory fixes counted in its mismatch tally).

### Pass A changes (§2.x, §4 intro)
- §2.1 — insert — ambiguity — whitespace-only auth header ≡ empty → 401 — auth.py:20
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 chars `A-Z0-9`, minted for error responses too — envelope.py:20,55
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, not host time — envelope.py:24
- §2.2 — insert — ambiguity — `response_type` only ever `object`/`array`/`error` — envelope.py:31,51,58
- §2.2 — insert — ambiguity — pagination `meta` only on paginated lists; batch invitation is `"array"` with bare `meta`; 204 carries no body — envelope.py:39,109
- §2.3 — insert — ambiguity — `limit`/`offset` must be whole integers (`2.5`, `?limit=` → 400); offset past `total_count` is an empty page; undeclared query params ignored — envelope.py:69,87
- §2.3 — insert — ambiguity — server insertion order is the final tie-break on every ordering; null `priority_score` sorts after scored rows — store.py:79, routes_decisions.py:96
- §2.3 — revise+insert — **mismatch** — dropped false "filters summarised again in §4"; pinned empty enum/boolean filter → 400, `segment`/`label_contains` verbatim, empty id-filters ≡ omission — validators.py:146,155,167
- §2.4 — insert — ambiguity — `id` is a canonical lower-case hyphenated UUID; every declared field always present (`null` when unset, never omitted); nothing beyond declared set + 4 common fields — serializers.py:11,23
- §2.4 — insert — **mismatch** — `version` advances once per request per row, not per field; a no-op write bumps nothing; all rows share one `updated_at`; representation is post-mutation — store.py:32,46, calc.py:102
- §2.5 — insert — ambiguity — clock endpoint answers 200/`object` with `data.current_utc`; `to_iso8601` accepts `Z`/offset/no-zone (UTC), else 400; may be set backwards — routes_ops.py:13, clock.py:41
- §2.6 step 4 — insert — ambiguity — ownership/SoD precede existence but are unevaluable against an absent row, so a missing resource falls through to the step-5 404 — routes_decisions.py:157, routes_repository.py:184, routes_readouts.py:104,184
- §2.6 step 5 — insert — ambiguity — the bullet list is a total order over **entity types, not arrival sites** (body FK of an earlier type outranks a path segment of a later one); absent/null/empty/wrong-typed body FK is a step-6 400, not 404; findings-list `theme_id` filter deliberately unchecked — validators.py:234, routes_studies.py:193, routes_repository.py:121,207
- §2.6 step 6 — insert — ambiguity — wrong-JSON-type rules (`3.0` invalid for integer, booleans not integers), `null` ≡ absent, undeclared body fields ignored, unparsable body ≡ `{}`, non-object JSON body → 400, enums invalid in query filters too — validators.py:16,25,71,146
- §2.8 — insert — ambiguity — rounded decimals serialize as JSON numbers, so `0.60` renders `0.6` — serializers.py:11
- §2.11 — revise — **mismatch** — a recompute counts as a mutation only when it lands a different value — calc.py:102
- §4 intro — insert — ambiguity — trailing slash tolerated; batch invitation 201 + array; the two test-driving endpoints and the metrics read answer 200 with a computed object — app.py:26, routes_studies.py:238,280, routes_ops.py:19,25

Verified clean, no change needed: §5 catalogue byte-exact against errors.py (51 ids, statuses, order, all reachable); all 119 serializer field names present; §2.6 existence order matches every call site; the four contractual list orderings match.

### Pass B changes (§3.1–§3.5, §3.9 settlement/metrics)
- §3.1 triage — insert — ambiguity — `reason` optional, unbounded, empty string stored verbatim; `method_override` enum-checked on every outcome (bad value → 400 even on `REJECTED`) but consumed only on `SUBMITTED → APPROVED` — routes_decisions.py:137-138,148-149
- §3.1 resubmit — insert — ambiguity — `triage_reason`/`triaged_at` deliberately not cleared — routes_decisions.py:169-176
- §3.1 lock — insert — ambiguity — a refused lock stores nothing; recomputed confidence discarded, `version`/`updated_at` unmoved — routes_decisions.py:66-74
- §3.2 pool create — insert — ambiguity — `name` unbounded; uniqueness is exact case-sensitive equality; collision check runs after all field validation — routes_pools.py:219-225
- §3.2 enrollment — insert — ambiguity — `external_ref` uniqueness uses the same exact case-sensitive comparison — routes_pools.py:253-258
- §3.3 study create — insert — ambiguity — neither pool posture nor the governing decision's lock state is consulted — routes_studies.py:52-96
- §3.3 guide write — insert — ambiguity — `guide_version_label` non-empty/unbounded; `guide_question_count` has no lower bound (0/negatives accepted) — routes_studies.py:104-105
- §3.3 guide approve — insert — ambiguity — the `PLANNED`/`GUIDE_APPROVED` status check precedes the guide check, so approving from `FIELDING` onward is `ERR_INVALID_STATE` — routes_studies.py:119-122
- §3.4 named invite — insert — ambiguity — contact cap read from the **participant's own pool** (study's pool only as fallback); stored `contacts_in_window` used un-recomputed; participant need not belong to the study's pool yet the reservation always hits the study's pool — routes_studies.py:203-206
- §3.4 batch selector — revise — **mismatch** — PRD claimed `created_at` "is unique per participant row"; ranking actually ends on server insertion order — calc.py:438-440
- §3.4 batch — insert — ambiguity — selector-created rows store `screening_answers` as null — routes_studies.py:228
- §3.5 screen — insert — ambiguity — either precondition failing is `ERR_INVALID_STATE` — routes_recruitments.py:334-337
- §3.5 screen score — insert — ambiguity — a row with no `screening_answers` scores exactly 0.00 (hence auto-invited rows screen out) — calc.py:136-149
- §3.5 schedule — insert — ambiguity — `moderator_user_id` required, non-empty, unbounded, never registry-checked — routes_recruitments.py:356
- §3.5 schedule window — revise — **mismatch** — the one-day grace boundary is **inclusive**, not exclusive; the bound is one-sided per edge (only `start` vs lower, only `end` vs upper) — routes_recruitments.py:368
- §3.5 complete — insert — ambiguity — `actual_duration_min` has no lower bound — routes_recruitments.py:415
- §3.5 complete — revise — ambiguity — completion moves no money (`RESERVED` kept); metrics are derived at read time, never stored — routes_recruitments.py:420-423, routes_studies.py:274-280
- §3.5 no-show — insert — ambiguity — `reason` required non-empty unbounded; the row's `reserved_cents` stays as the forfeiture record — routes_recruitments.py:433,444
- §3.5 withdraw — insert — ambiguity — `reason` likewise required and non-empty — routes_recruitments.py:461
- §3.9 settlement — insert — ambiguity — `expected_pool_version` required integer, unbounded; zero/negative simply fail the equality check with 412 — routes_pools.py:308,317
- §3.9 chronological walk — insert — ambiguity — third sort key is server insertion order — routes_pools.py:350-354
- §3.9 close-out — insert — ambiguity — `study_id` appended even when the candidate set was empty; both modes answer 200 with the pool representation; every successful run bumps pool `version` by 1 even when nothing changed — routes_pools.py:326-331,372
- §3.9 metrics — revise — ambiguity — payload carries exactly the five named keys and does not echo `study_id` — routes_studies.py:279

Pass B declined two of pass A's notes as already-pinned by pass A in §2.2/§2.3 (null-`priority_score` ordering; batch response meta shape) rather than duplicating them.

### Pass C changes (§3.6–§3.8, calc-bearing §3.9, plus 2 cross-territory fixes)
- §3.6 ¶3 — insert — ambiguity — with several qualifying `GRANTED` records, the **earliest-created** supplies `retention_until` — routes_consent.py:109-119
- §3.6 hop 3 — insert — ambiguity — hops 4 and 5 run only if hop 3 actually moved a `status` or `evidence_strength` — cascade.py:118-122
- §3.6 hop 4 — revise — **mismatch** — trigger is any finding whose `status` **or** `evidence_strength` changed, not only retracted ones — cascade.py:118-126
- §3.6 hop 5 — revise — **mismatch** — likewise decisions reachable from studies owning any *changed* finding — cascade.py:129-138
- §3.6 sweep — revise — ambiguity — pinned the five sweep passes and their fixed order (consents one-at-a-time → due artifacts as one set → follow-ups → participants → pools), the previously unmentioned pool pass (counters, `incentive_available_cents`, posture), the `created_at`/insertion walk order, and that the six counters count distinct rows — cascade.py:155-196
- §3.6 ¶4 — insert — ambiguity — revoke `reason` required, non-empty, unbounded — routes_consent.py:68
- §3.7 ¶1 — insert — ambiguity — `parent_theme_id` treated as absent for `null`, `""`, wrong type → root theme, not an error — routes_repository.py:48, validators.py:234-243
- §3.7 ¶3 — insert — ambiguity — the three link guards fire in §2.6 order (finding state → artifact lifecycle → study match); purged artifact on a `PUBLISHED` finding gives `ERR_INVALID_STATE` — routes_repository.py:126-132
- §3.8 ¶1 — insert — ambiguity — `expected_study_version` required integer, unbounded both directions — routes_readouts.py:51
- §3.8 acceptance — revise — ambiguity — `reuse_count` rises by exactly one per theme per accepted readout regardless of how many cited findings map to it or share an ancestor — routes_readouts.py:145-159
- §3.8 follow-ups — insert — ambiguity — no state precondition on creation; any readout status incl. `DRAFT`/`SUPERSEDED`; the readout is not mutated — routes_readouts.py:162-178
- §3.9 `cycle_time_days` — revise — ambiguity — insertion-order final tie-break after `(delivered_at, created_at)` plus the `delivered_at is not null` predicate — calc.py:451-457
- §3.9 `published_findings` — revise — **mismatch** — deleted the false "as are superseded readouts wherever readouts are counted"; the readout `status` filter applies to `cycle_time_days` alone, while the acceptance and follow-up terms walk every readout, so follow-ups under a `SUPERSEDED`/`DRAFT` readout do count — calc.py:471-481
- §4 row `POST /readouts/{id}/follow-ups` — revise — **mismatch** — "against an accepted readout" → "against a readout in any status" — routes_readouts.py:162
- **§2.6 step 9 (cross-territory)** — revise — **mismatch** — "guards study fielding and readout response" contradicted impl and §3.8's deferral paragraph; scoped to a response whose `outcome` is `ACCEPTED`, noting `DEFERRED` never consults the lock — routes_readouts.py:114
- **§2.3 ¶3 (cross-territory)** — revise — **mismatch** — "an empty value is a real filter that matches nothing" holds only for `segment` (equality); `label_contains` is a substring test so `?label_contains=` matches every theme. Split the sentence per filter — routes_repository.py:85 vs routes_pools.py:107

Pass C verified-but-no-edit (already pinned upstream): `ERR_DECISION_LOCKED` ACCEPTED-only scope in §3.8; `EVIDENCE_LOCKED` → `DRAFT`/`PROVISIONAL` silent revert; global theme-`label` uniqueness and its §2.6-step-12 precedence over the depth cap; all string maxima (`statement` 500, `recommendation` 1000, `description` 500, `excerpt_ref` non-empty, `retention_days` ≥ 1); `decision_evidence_confidence`'s 1.00 divisor and 1.00 ceiling (walk order immaterial — sum of pre-rounded terms); `_theme_own_weight` `PUBLISHED`-only with per-term 2dp rounding and the ancestor-to-root reuse walk; `strength_variant` derived from `status`; `retention_horizon` "tighter of the two" and `ARTIFACT_SCOPE`'s `PII_NOTE → PII_QUOTE`; insertion-order tie-breaks globally pinned by §2.3. All 13 calc.py formulas walked — the §3.1–§3.5 prose (priority score, method table + `MEASUREMENT`/5,000 override, screen score cap + disqualifier gate, pool utilization/posture `>= 0.95` / `>= 0.80` / ratio `> 0.50`, surcharge tiers with ceil-to-cent, participant window with exclusive lower bound, study counters, batch selector ranking) matches the code exactly.

### Orchestrator verification of Step 9 output
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD.md` (`cmp` differs; +16,538 chars) — the scan demonstrably ran.
- 490 lines, 28 headings, §1–§5 all intact, 4 balanced code fences.
- Ends at a real section boundary: last content line is the §5 row `` | `ERR_DUPLICATE_LABEL` | 409 | ``.
- Error-code inventory preserved end to end: **51 distinct `ERR_*` in `PRD.md`, 51 in `PRD_COMPLETED.md`, 51 in `implementation/errors.py`** — no code dropped or invented by the three passes.
- No stray `worklog.md` or report `.md` under `workspace/` (memory: worklog appends drift into `workspace/` when Bash cwd persists — all appends in this run used absolute paths).

**Pipeline complete.** Steps 1–7 and 9 executed; Step 8 skipped on its stated skip condition.

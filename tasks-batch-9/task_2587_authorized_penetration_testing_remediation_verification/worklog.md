# Worklog — task_2587_authorized_penetration_testing_remediation_verification

## Step 1: Create task directory — 2026-09-03T15:11:43.684Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification` and its `workspace/` subdirectory. Index 2587 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T17:16:00.000Z

All three scaffold artifacts are complete and lint clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/`)

| File | Lines | Bytes | Top-level key(s) | Ends at |
|---|---|---|---|---|
| `SCAFFOLD.yaml` | 2232 | 140,860 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys) | end of §1.7 `RemediationOwner.shared_operations` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2399 | 158,652 | `scaffold_difficulty_design` only | last `assert:` bullet of the hour-ledger instance |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6490 | 412,024 | `scaffold_corner_design` only | last `assert:` bullet of the consistency_model instance |

Each file was built with chunked `cat >>` appends, `yaml.safe_load`-validated after every chunk.

## Surface (§1.0–§1.7)
`domain_name: pentest-assurance`, `api_prefix: /pentest`. 13 entities, 55 endpoints, 13 state machines (Engagement carries two parallel axes), 3 `concurrency_rules`, 13 calculations, 65 validation rules (strict priority ladder 1→65), 75 error codes, 5 roles (Tester is `entity_backed:Tester`), `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `complexity_layers: [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, `consistency_model: immediate`.

## §1.8 depth probe
9 rule_ids × 2 instances = 18 instances: calculation-formula depth, parallel/cyclic state-machine depth, multi-link cascades (6-link emergency pause, 5-link closure sign-off), validation-priority conflicts, inclusive/exclusive boundaries, cross-entity guarded transitions, temporal collision with cooldown padding, half-open interval aggregation, and two conservation invariants (plan risk-point ledger, engagement hour ledger).

## §1.9 breadth probe — 102 instances (76 real recipes + 26 `excluded_because` stubs)
entities 14/0 · state_machines 16/6 · calculations 8/9 · validations 19/5 · endpoints 5/2 · errors 6/0 · rbac 4/0 · cross_cutting_layers 3/4 · consistency_model 1/0.

Endpoint-surface audit result: **all 75 error ids are triggerable** across §1.8 ∪ §1.9 (verified by script against the §1.6 catalog); every stub cites a §1.8 instance that exists by name; no name collisions across the union of both design files.

## Lint verdict (verbatim, final run)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  1500

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

An earlier run reported 11 `(d) capture JSONPath unresolvable` violations — all captures naming fields that don't exist in §1.1 (`Finding.severity_rating`, `Engagement.roe_state`/`started_at`/`assurance_score`, `TestPlan.state`, `ScopeItem.state`/`decided_by_user_id`, `RulesOfEngagement.state`). Fixed to the declared names (`severity_score`, `authorization_state`, `execution_state`, `provisional_assurance_score`, `status`, `decision_note`) with the dependent asserts rewritten. Two pre-computed literals were also corrected during self-audit: `TestPlan.total_risk_points` is finding-derived (so it stays 0 in the OCC instance, not 148.00) and the canonical scope candidate scores 89.80, not 120.00.

No sibling task directory was read, listed, globbed or grepped at any point.

## Step 3: Copy shared files — 2026-09-03T17:17:28.383Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:29:00.000Z

The PRD is complete and all three hard contracts pass.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/workspace/PRD.md`

**484 lines / 104,757 bytes.** Built with 9 chunked appends plus 2 targeted edits — no single-Write truncation risk. File ends at a real boundary: the final row of the §5 error table, followed by a trailing newline.

## Section list
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Record Identity, Audit Stamps and Versioning · 2.5 The Logical Programme Clock · 2.6 Numeric Precision · 2.7 Stale-Version Guards on Programme Writes · 2.8 Order of Rejection · 2.9 Cascade Discipline and Cross-Aggregate Consistency · 2.10 Segregation of Duties · 2.11 Read Channels and Path Resolution
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Programme Foundations: The Asset Inventory and the Tester Roster · 3.2 Opening the Annual Plan and Scoring Candidate Scope · 3.3 Scope Decisions and the Coverage Gate · 3.4 Chartering an Engagement and Authorizing the Test · 3.5 Staffing, Least-Privilege Access and the Hour Ledger · 3.6 Fieldwork: Reporting Findings, Rating Severity and Real-Time Critical Alerts · 3.7 Triage and the Conserved Risk-Point Ledger · 3.8 Remediation, Retest Verification and Closure · 3.9 Emergency Stop, Engagement Wind-Down and Programme Trend Analysis
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Verified counts (all by grep/parse against SCAFFOLD.yaml, not impression)
- **Entities: 13/13** documented, and every field of every one is present in backticks — Asset 11, TestPlan 12, ScopeItem 10, Engagement 14, RulesOfEngagement 10, AuthorizedTarget 8, Tester 9, TesterAssignment 11, Finding 17, CriticalAlert 8, Remediation 11, RetestVerification 11, TrainingRecommendation 10 = **122/122 field names, 0 missing**.
- **Endpoints: 55/55** rows in the §4 table (5 pipes per row = exactly 4 columns).
- **Endpoint inputs: 81/81** identifiers present in backticks (29 query-param names + 52 body/path identifiers), 0 missing.
- **Validations: 65/65** — all 65 distinct `error_id`s appear inside the §2.8 ordered rejection ladder, so every `priority` has an expressed relative order.
- **Errors: 75/75** in the §5 table (3 pipes = 2 columns), **and 75/75 also mentioned in §2/§3 narrative** (checked against the text before `## 4.`).
- **State transitions: 54/54** expressed (40 matched a mechanical `FROM -> TO` regex; the remaining 14 were manually confirmed as prose-form renderings, e.g. "Withdrawing moves a candidate at `PROPOSED` or `DEFERRED` to `WITHDRAWN`").
- **Concurrency rules: 3/3** in §2.7 with write_endpoint + occ_field + error_id + HTTP 412 all named.
- **Calculations: 12/12** expressed in operator-free prose; every constant from every `constants` block verified present in narrative (48-value spot list, 0 absent).
- **Roles: 5/5** named in backticks with `identity:` translated (Tester entity-backed, other four opaque).

## Contract reports
```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body/input: 52 required, 52 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 65 checked, 65 expressed in prose (§2.8 ladder + per-workflow), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 54 checked, 54 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 65 checked, 65 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 checked, expressed, 0 missing
- entities[].fields[] structured content: 122 checked, reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (PASS/FAIL/PARTIAL, PAUSE/TERMINATE,
  ACKNOWLEDGED/ESCALATED, CLEARED vs FLAGGED/EXPIRED, RISK_ACCEPT/REVOKE,
  PROVISIONAL/FINAL), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 943
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words (the only two " about " hits are "explicit about" and "precise about"); no meta-instruction leakage (scanned for difficulty/benchmark/scaffold/Expert/test_recipe/"harder than" — 0 hits); the two withheld design files were never opened.

Two precision gaps I found during Contract 2 and closed: (1) `hours_reserved`/`hours_consumed`/`hours_available` were only stated as increments, so I added their standing set-based definitions in §3.5; (2) the `VERIFIED -> SUPERSEDED` transition's `outcome IN {FAIL, PARTIAL}` precondition was implicit, so I made it explicit in §3.8.

## Last 3 lines
```
| `ERR_RESIDUAL_NOTE_REQUIRED` | 422 |
| `ERR_PLAN_ENGAGEMENT_LIMIT_REACHED` | 409 |
| `ERR_ENGAGEMENT_HOURS_EXCEEDED` | 422 |
```

**Orchestrator anti-truncation verification (independent):** `wc -l` = 484, `wc -c` = 104757. `tail -12` shows twelve complete `| ERR_* | NNN |` table rows, i.e. the file ends at a real section boundary (last row of the §5 error catalogue), not mid-sentence. `grep -n '^#'` confirms all 5 top-level sections and all 11 §2 + 9 §3 subsections are present in order. Leak grep for `harder than expert|difficulty|scaffold|benchmark|test_recipe` returned 0 hits. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T18:03:00.000Z

Implementation complete and smoke-verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` (exec) | 10 | guarded `pip install` (only when flask missing), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 76 | app factory, blueprint mounting under `/pentest`, `ApiError` handler, 404/405/500 handlers |
| `util.py` | 94 | ISO-8601 parse/format (3 fractional digits), Decimal helpers, day/hour arithmetic |
| `errors.py` | 115 | full ~88-entry `error_id -> HTTP status` table + default messages + `ApiError` |
| `store.py` | 47 | 13 in-memory dicts, logical clock (`2026-08-01T00:00:00Z`), id/seq generators |
| `envelope.py` | 43 | `meta`/`response_type`/`data` envelope, `req_` + 20 uppercase-alnum request ids |
| `auth.py` | 43 | `X-User-ID`/`X-User-Role` (Band 1), `authorize()` / `require_role()` |
| `validate.py` | 196 | Band 3 typed field extractors + pagination |
| `calc.py` | 271 | all 13 calculations with pinned rounding modes and constant tables |
| `core.py` | 368 | version/`updated_at` stamping, lookups, ledgers, ranking, posture, the four cascades |
| `serialize.py` | 282 | per-entity response shapes, verbatim echo of client instants, read-time `overdue_flag` |
| `resolve.py` | 76 | Band-2 FK resolvers (per-entity 404 ids), pagination, list filters |
| `routes/` (13 files) | 1544 | assets 72, clock 18, testers 106, plans 169, scope 107, engagements 168, roe 187, assignments 154, findings 198, alerts 59, remediations 127, retests 126, `__init__` 0 |

Total 3113 lines. Every file passes `ast.parse`. No `sqlite`/`open(`/`json.dump`/`/tmp`/`pickle` anywhere — storage is pure dicts, empty at boot, zero seeded records.

## Endpoint count: 55 (exact)

54 under `/pentest` + `POST /_clock/set_current_utc`, matching PRD §4 one-for-one.

## Structure

**Validations** follow PRD §2.8's 11-band ladder literally, band by band, inside each handler: `authorize()` (Band 1) -> path-id resolvers (Band 2) -> `validate.py` extractors (Band 3) -> body FK resolvers in PRD's declared field order (Band 4) -> OCC (Band 5) -> state preconditions (Band 6) -> uniqueness (Band 7) -> testing-authorization safety (Band 8) -> SoD (Band 9) -> temporal/capacity (Band 10) -> fiscal last (Band 11). Discriminator enums are parsed before action-level role reservations (`REPORT`/`CLOSE` -> ProgramManager, `TERMINATE` -> ComplianceOfficer, `RISK_ACCEPT`/`REVOKE_RISK_ACCEPTANCE` -> ComplianceOfficer) so the 400/403 order is consistent across every action endpoint.

**OCC** is three guards checked strictly before state preconditions: `expected_test_plan_version` -> `ERR_STALE_PLAN_VERSION`, `expected_engagement_version` -> `ERR_STALE_ENGAGEMENT_VERSION` on both findings and assignments. Omission is a Band-3 400. `core.touch()` keys a per-request `g.touched` set on record id, so a record's `version` advances by exactly 1 per request no matter how many cascade links touch it.

**Cascades** live entirely in `core.py`, run synchronously before the response is serialised: `cascade_pause` (six links), `cascade_terminate`, `cascade_resume` (never revives `EXCLUDED` targets), `cascade_close_finding` (closure links 3-5), plus `revoke_assignment` as the single hour-settlement path reachable four ways, and `bubble_up` so a TestPlan only ever reaches `CLOSED` derivatively.

## Smoke-test evidence

Four scenario suites ran against `bash start.sh` on unique high ports (28289, then 31477 for fresh-store scenarios), each killed by exact captured PID (`kill 4039322`, `4057364`, `4057794`, `4058373`, `4059240`, `4059571`) — no pattern-based kill used. Ports confirmed free afterwards.

Envelope + rejection ladder:
```
--- no headers 401
{"meta": {"api_request_id": "req_TJ9IM7UE7AD1BYO9T5XG", "api_request_timestamp": "2026-09-03T17:52:43.742Z"},
 "response_type": "error", "data": {"error_id": "ERR_MISSING_AUTH_HEADERS", ...}}
--- missing field 400   ERR_INVALID_REQUEST  "Field 'name' is required."
--- bad pagination 400  ERR_INVALID_PAGINATION
--- wrong role 403      ERR_UNAUTHORIZED
```
Create + read + list:
```
--- asset t1 201  data: {"id": "bc70f11e-...", "created_at": "2026-09-10T12:00:00.000Z", "version": 1,
    "exposure_score": 88.5, "exposure_state": "MONITORED", "open_finding_count": 0, ...}
--- list assets 200  meta: {..., "limit": 10, "offset": 0, "total_count": 1, "has_more": false}
```
Full happy path (plan -> scope -> activate -> engagement -> ROE -> target -> sign -> tester -> assignment -> provision -> START -> finding -> alert -> ack -> triage -> remediation -> submit -> retest -> sign-off -> fieldwork -> report -> trend -> close) all green, with invariants verified live:
- hour ledger `200.0 = 100.0 + 0.0 + 100.0` after provision, back to `200/0/0/200` after close
- risk-point ledger `total 40 = open 0 + closed 40 + accepted 0 + duplicate 0`; second scenario `48 = 8 + 40 + 0 + 0`
- asset posture `MONITORED -> ELEVATED -> CLEARED` with `last_cleared_at` stamped
- TestPlan reached `CLOSED` only via bubble-up

Boundary and cascade checks that all returned the PRD-mandated code:
`ERR_STALE_PLAN_VERSION` 412, `ERR_COVERAGE_BELOW_MINIMUM` 422 (33.33 < 60, and no state was persisted on the failed activation), `ERR_NO_AUTHORIZED_TARGETS` 422, `ERR_TECHNIQUE_NOT_ALLOWED` 422 (both bad member and empty list), `ERR_ROE_ALREADY_EXISTS` 409, `ERR_WINDOW_OUTSIDE_ENGAGEMENT` 422, `ERR_TARGET_WINDOW_COLLISION` 409 at exactly +24h on a NETWORK asset while +24h+1s passed (inclusive widened bounds), half-open assignment intervals touching end-to-start accepted while a third overlap gave `ERR_TESTER_CAPACITY_EXCEEDED` 409, `ERR_LEAD_QUALIFICATION_NOT_MET` before `ERR_ENGAGEMENT_HOURS_EXCEEDED`, `ERR_ACTOR_NOT_OWNER` 403, `ERR_SOD_VERIFIER_CONFLICT` / `ERR_SOD_SIGNOFF_CONFLICT` 422, `ERR_VERIFIER_ROLE_NOT_PERMITTED` 422, `ERR_RESIDUAL_NOTE_REQUIRED` 422, `ERR_EXTENSION_LIMIT_REACHED` 409 after two extensions, `ERR_RETEST_ALREADY_SIGNED_OFF` 409, `ERR_ENGAGEMENT_SUSPENDED` / `ERR_ENGAGEMENT_ALREADY_TERMINATED` / `ERR_ENGAGEMENT_NOT_SUSPENDED` 409, per-entity 404s.

Notable computed values confirmed: CRITICAL severity `10.0`/band/40 points with an alert raised and `immediate_action_required` true; MEDIUM `6.7` with zero alerts; HIPAA cap applied (`MEDIUM 60d -> sla_days 45`); INTERNAL ack deadline `+240m` with a late ack producing `ESCALATED`/level 2 then `ACKNOWLEDGED` at level 2; `verifier_tester_id: null` when a ComplianceOfficer verifies an `EVIDENCE_ONLY` remediation; `days_late 31`; FAIL and PARTIAL both return the remediation to `ASSIGNED` with evidence cleared, PARTIAL adding 14 days without touching `extension_count`; NETWORK cooldown 24h / CLOUD 12h / APPLICATION 0h.

One PRD-ordering subtlety worth flagging: a second remediation on a finding already at `REMEDIATION_ASSIGNED` returns `ERR_FINDING_NOT_TRIAGED` (409) rather than `ERR_REMEDIATION_ALREADY_EXISTS`, because Band 6 (state) precedes Band 7 (uniqueness) in §2.8. `ERR_REMEDIATION_ALREADY_EXISTS` remains reachable when the prior remediation is non-`CLOSED` but the finding is back at `TRIAGED`.

## Step 5: Generate unit tests — 2026-09-03T19:33:00.000Z

(Launched concurrently with Step 6 in a single assistant message; recorded after Step 6 because it finished later.)

Step 5 is complete: the full unit-test infrastructure and test suite for task_2587 now exist at the task root, with every test traceable to exactly one design instance.

## Files written (all at the TASK ROOT)

**Stage 1 — `test_helpers/`** (completed earlier in this task, unchanged): `constants.py` 231, `api_errors.py` 230, `api_client.py` 406, `factories.py` 300, `assertions.py` 359, `fixtures.py` 291, `test_users.py` 90, `types.py` 46, `__init__.py` 104.

**Stage 2 — `test_suite/`** (`conftest.py` 75):

| file | lines | tests | queue / §1.9 section |
|---|---|---|---|
| test_01_prioritisation_and_assurance_variants.py | 243 | 6 | A |
| test_02_severity_and_training_formulas.py | 290 | 8 | A |
| test_03_state_machine_cycles.py | 371 | 10 | A |
| test_04_transitive_cascades.py | 305 | 10 | A |
| test_05_validation_precedence.py | 239 | 6 | A |
| test_06_boundary_values.py | 245 | 8 | A |
| test_07_cross_entity_gates.py | 253 | 8 | A |
| test_08_interval_conventions.py | 271 | 7 | A |
| test_09_conserved_ledgers.py | 288 | 9 | A |
| test_10_entity_shapes.py | 520 | 14 | B / entities |
| test_11_state_machines.py | 882 | 16 | B / state_machines |
| test_12_calculations.py | 553 | 8 | B / calculations |
| test_13_validations.py | 1200 | 19 | B / validations |
| test_14_endpoints.py | 399 | 5 | B / endpoints |
| test_15_errors.py | 573 | 6 | B / errors |
| test_16_rbac.py | 549 | 4 | B / rbac |
| test_17_cross_cutting.py | 339 | 3 | B / cross_cutting_layers |
| test_18_consistency.py | 123 | 1 | B / consistency_model |

**Total: 148 tests across 18 files.**

## Instance coverage

- **Queue A (§1.8):** 18 / 18 instances translated, 72 tests, minimum 3 tests per instance (target was >=2). No skips.
- **Queue B (§1.9):** 76 / 76 non-stub instances translated, 76 tests, >=1 test each — entities 14, state_machines 16, calculations 8, validations 19, endpoints 5, errors 6, rbac 4, cross_cutting_layers 3, consistency_model 1.
- **Skipped: 0 whole instances** under the PRD-first two-condition filter. The only untested §1.9 entries are the **26 `excluded_because:` stubs** (calculations 9, state_machines 6, validations 5, cross_cutting_layers 4, endpoints 2), which by design get no tests — verified programmatically that no stub name appears in any `Design:` tag.
- Three **sub-assertions** were dropped or PRD-corrected rather than weakening a whole instance: (1) the `started_at` stamp claimed by the START instance — the identifier does not appear anywhere in PRD.md; (2) the consistency instance's `exposure_state == BASELINE` — PRD.md:190 says a fresh asset opens at `MONITORED`, so the test asserts `MONITORED`; (3) the same instance's `provisional_assurance_score == 75.00` read mid-fieldwork — PRD stamps that field only when fieldwork completes, so the test asserts it is still `null`.

## Verification run

- `tests=148 problems=0 distinct_design_tags=94` from the citation/tag checker (94 = 18 queue-A + 76 queue-B): every test has a docstring, exactly one trailing `Design:` line, >=1 verbatim `PRD:` citation that literally substring-matches a single physical line of PRD.md and is >=8 words.
- All 94 tags resolve by set difference against the source yamls; 0 unknown tags, 0 stub tags, 0 uncovered live instances.
- `python3 -m py_compile test_suite/*.py test_helpers/*.py` clean; no unused imports (AST scan per file); zero occurrences of `pytest.mark.skip` / `xfail` / `pytest.skip`; zero occurrences of the word "scaffold".
- No servers launched, no `pkill` used, `workspace/implementation/` never read or touched.

## Proof of path

```
$ ls -d .../task_2587_.../test_helpers .../task_2587_.../test_suite
/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/test_helpers
/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/test_suite

$ ls .../task_2587_.../workspace/
INSTRUCTION.md
PRD.md
implementation
```

No stray `test_helpers/` or `test_suite/` under `workspace/`.

**Orchestrator independent verification:** `grep -c 'def test_'` across `test_suite/*.py` sums to 148; `grep -c 'Design:'` sums to 148 (one tag per test). `ls -d` confirms both directories are at the task root and `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray copies to relocate.

## Step 7: Run tests and iterate — 2026-09-03T20:04:00.000Z

All 8 parallel rounds now pass 148/148. `workspace/implementation/` was never modified — every defect was in the test artifact.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, `setsid nohup`, no early exit).

**Sweep 1:** every round 144/155 with the *same* 5-item union (fully deterministic, no flakiness, no reaping — no `Terminated` logs, rounds finished at independent times).

**Tests deleted:** none. All five failures traced to PRD-verbatim rules; four were test bugs and one was an error-precedence ambiguity handled with the permitted `one_of` relaxation.

**Fixes to `test_helpers/`**
- `test_helpers/fixtures.py` — renamed the helper `test_plan_version` -> `read_plan_version`. Its `test_` prefix made pytest collect it as a test in all 7 modules that imported it, producing 7 phantom "fixture 'plan_id' not found" errors per round (this is why `total` was 155, not the intended 148). Propagated to `test_helpers/__init__.py` and the 7 importing suites.
- `test_helpers/assertions.py` — added `assert_error_id_in()` wrapping the framework's `validate_error_is_one_of`; exported from `test_helpers/__init__.py`.

**Fixes to `test_suite/`**
- `test_05_validation_precedence.py` — `_excluded_target_after_the_window_closed` pushed the clock to 2026-10-05, five days past `window_end`. PRD.md:270 makes the *first* authorization-of-testing check "at least one authorized target ... must cover the current instant ... ERR_NO_OPEN_TESTING_WINDOW", and a target's window must nest inside the engagement's (`ERR_WINDOW_OUTSIDE_ENGAGEMENT`), so an expired engagement window can never be the loser to an exclusion — `ERR_NO_OPEN_TESTING_WINDOW` always answers first. Renamed to `_excluded_target_inside_the_open_window`, dropped the clock advance, and per partial-coverage handling replaced the unreachable `!= ERR_OUTSIDE_TESTING_WINDOW` sub-assertion with `!= ERR_NO_OPEN_TESTING_WINDOW` (PRD's "even an excluded target proves that an authorized window covered this moment"). The `ERR_TARGET_EXCLUDED` and `!= ERR_TARGET_NOT_AUTHORIZED` assertions are unchanged.
- `test_11_state_machines.py::test_termination_closes_both_axes_and_refuses_a_second_stop` — plan version corrected 5 -> 6. PRD.md:88 names five plan-version bumps (propose, decide, activate, create engagement) plus PRD.md:334's bubble-up close, so from `version` 1 at creation the terminated plan lands on 6. Implementation was right.
- `test_15_errors.py::test_engagement_creation_checks_the_plan_state_before_the_candidate_state` — the test re-`APPROVE`d a candidate the scenario builder had already approved; PRD.md:218 declares approval only from `PROPOSED` or `DEFERRED`, so the server correctly returned `ERR_SCOPE_ITEM_NOT_PENDING` and the setup died. Replaced the redundant call with a status assertion on the already-approved candidate.
- `test_15_errors.py::test_the_remediation_lifecycle_refuses_every_out_of_order_call` — a second remediation on a finding already at `REMEDIATION_ASSIGNED` trips both PRD.md:144 (Band 6, `ERR_FINDING_NOT_TRIAGED`) and PRD.md:300/150 (Band 7, `ERR_REMEDIATION_ALREADY_EXISTS`). Band 6 precedes Band 7 in §2.8, yet §3.8 states the uniqueness refusal unconditionally, and no PRD sentence says which pre-empts; there is in fact no reachable state where a finding holds a non-`CLOSED` remediation and is still `TRIAGED`. Relaxed to `assert_error_id_in([ERR_REMEDIATION_ALREADY_EXISTS, ERR_FINDING_NOT_TRIAGED])` — the sanctioned coverage correction, not a downgrade to an HTTP-status check.

**Fixes to `implementation/`:** none.

**Final per-round figures (from `workspace/implementation/results.{1..8}.json`):** 148/148, 148/148, 148/148, 148/148, 148/148, 148/148, 148/148, 148/148 — 0 failed in every round. No `skip`/`xfail`/`pytest.skip` anywhere in the artifact; `def test_` count is 148, matching collection exactly.

**Orchestrator independent verification of the sweep artifacts:** all eight `workspace/implementation/results.{1..8}.json` exist and parse; each reports `passed == total == 148`. The baseline sweep was also independently observed by the orchestrator at 144/155 in all eight rounds before the fixes, confirming the failure set was deterministic rather than load-induced.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 2 `test_helpers/` fixes and 4 `test_suite/` fixes, so the zero-fix skip condition does not hold. Although `implementation/` was never modified, two of the Step 7 items are PRD-ambiguity signals rather than pure fixture bugs (the §2.8 Band 6 vs Band 7 precedence silence behind the `one_of` relaxation, and the unreachable `ERR_OUTSIDE_TESTING_WINDOW`-vs-exclusion ordering), so Step 8 is given the diff to pin those spots against what the implementation actually does.

## Step 8: Finalize PRD — 2026-09-03T20:10:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2587_authorized_penetration_testing_remediation_verification/workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 484 lines / 104,757 bytes. PRD_FINALIZED.md: 484 lines / 105,049 bytes.
- Line-count delta: 0 (0.0%). Byte delta: +292 (+0.28%). `diff` reports exactly one changed line (PRD line 300, §3.8); tail intact.

## Changes
- §3.8 Remediation, Retest Verification and Closure — revise — pinned that the finding's `TRIAGED` precondition is evaluated **before** the one-live-remediation uniqueness scan, so a non-`TRIAGED` finding yields `ERR_FINDING_NOT_TRIAGED` even when a live (non-`CLOSED`) remediation also exists — `implementation/routes/remediations.py:37-41`.

## Per-edit pre-edit search log
**Edit 1 — §3.8 precedence of `ERR_FINDING_NOT_TRIAGED` vs `ERR_REMEDIATION_ALREADY_EXISTS`**
- (a) Subject: order of the finding-status precondition and the remediation-uniqueness refusal on `POST /remediations`, plus every other producer/consumer of those two error ids and of the `TRIAGED` / `REMEDIATION_ASSIGNED` finding statuses.
- (b) Paths enumerated (grepped `ERR_FINDING_NOT_TRIAGED|ERR_REMEDIATION_ALREADY_EXISTS|TRIAGED|REMEDIATION_ASSIGNED` across all of `implementation/`, then read each hit): `routes/remediations.py:36-41` (status check first, then uniqueness loop — the Step 7 site), `routes/remediations.py:60` (finding -> `REMEDIATION_ASSIGNED`), `routes/remediations.py:102-104` (submit: `REMEDIATION_ASSIGNED` -> `REMEDIATION_SUBMITTED`), `routes/engagements.py:116` (the *other* `ERR_FINDING_NOT_TRIAGED` producer — the `FIELDWORK_COMPLETE` -> `REPORTED` gate, a different operation), `routes/retests.py:63-79` (FAIL/PARTIAL reverts remediation to `ASSIGNED` and finding to `REMEDIATION_ASSIGNED`; PASS -> `RETEST_PASSED`), `routes/findings.py:140-197` (triage: `ACCEPT` and `REVOKE_RISK_ACCEPTANCE` both land on `TRIAGED`; `MARK_DUPLICATE`/`RISK_ACCEPT` accept `REPORTED` *or* `TRIAGED`), `errors.py:48,57` (both 409).
- (c) Wording adjustments made: (1) scoped the new clause to "an assignment naming a finding" so it cannot be read as re-ordering the unrelated `ERR_FINDING_NOT_TRIAGED` raised by the move-to-reported gate at `routes/engagements.py:116`; (2) phrased the uniqueness relationship as "whether or not a live remediation also exists" rather than asserting any reachable `TRIAGED`-with-live-remediation state — the enumerated `findings.py`/`retests.py` transitions show no such state is reachable, so a stronger claim would have been a false universal; (3) anchored to "§2.8's ladder requires" so the sentence reinforces the existing Band 6 #17 -> Band 7 order instead of introducing a competing local rule.

## Items that correctly produced NO PRD edit
- `test_helpers/fixtures.py` `test_plan_version` -> `read_plan_version` rename and the new `assert_error_id_in` wrapper: pure pytest-collection / helper infrastructure, no PRD counterpart.
- `test_15_errors.py` redundant re-`APPROVE`: pure fixture bug; PRD.md:129 (Band 6 #3) already pins `ERR_SCOPE_ITEM_NOT_PENDING`.
- `test_05_validation_precedence.py` window/exclusion precedence: PRD.md:270 already states the first check ignores target state and refuses only with `ERR_NO_OPEN_TESTING_WINDOW`, and PRD.md:156 already forces target windows to nest inside the engagement window, so the ordering is fully determined — verified impl matches; no silence to pin.
- `test_11_state_machines.py` plan `version` 5 -> 6: determined by PRD.md:88 (five plan bumps) + PRD.md:328 (TERMINATE evaluates the plan bubble-up "exactly as an ordinary close would") + PRD.md:334 ("The plan's `version` advances when it closes"). Test was wrong, PRD and impl agreed.

**Orchestrator independent verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk (`300c300`) inserting the Band-6-before-Band-7 precedence sentence into §3.8; byte size 105,049 vs 104,757 confirms the file is not a bare copy and did not lose its tail.

## Step 9: Complete PRD — 2026-09-03T21:05:00.000Z

**Orchestrator decision recorded before running:** a single monolithic Step 9 subagent reliably under-covers a 3113-line implementation (and in the worst case leaves `PRD_COMPLETED.md` byte-identical to its source, meaning the scan never really ran). Step 9 was therefore executed as **three sequential file-partitioned passes**, each making targeted `Edit` calls against one shared `workspace/PRD_COMPLETED.md` that the orchestrator seeded with `cp PRD_FINALIZED.md PRD_COMPLETED.md`. Each pass was told what the previous passes had already pinned so it would not re-litigate them.

Partitioning:
- **Pass 1 — cross-cutting machinery:** `app.py`, `envelope.py`, `auth.py`, `errors.py`, `store.py`, `util.py`, `validate.py`, `resolve.py`, `serialize.py`, `routes/clock.py`
- **Pass 2 — calculation/core layer + early routes:** `calc.py`, `core.py`, `routes/assets.py`, `routes/testers.py`, `routes/plans.py`, `routes/scope.py`
- **Pass 3 — remaining route surface:** `routes/engagements.py`, `roe.py`, `assignments.py`, `findings.py`, `alerts.py`, `remediations.py`, `retests.py`

### Pass 1 report (machinery)

File state: `PRD_FINALIZED.md` 484 lines / 105,049 chars -> `PRD_COMPLETED.md` 497 lines / 114,480 chars (+13 lines, +9,431 chars). 15 hunks, all inside §2.1–§2.8, the §4 preamble and the §5 table; tail intact (error catalogue now 78 rows = exactly the 78 ids in `errors.py`).

Counts: **ambiguity-pins 18, mismatch-revisions 3.**

- §2.1 — revise — ambiguity — surrounding whitespace on both auth headers is trimmed before use (role matched, `X-User-ID` stored/compared trimmed); role match is exact and case-sensitive — `auth.py:26-37`
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9`, length 24, regenerated per response incl. errors — `envelope.py:10-14`
- §2.2 — revise — ambiguity — `api_request_timestamp` is real wall-clock, explicitly **not** the logical clock of §2.5 — `envelope.py:20`
- §2.2 — insert — ambiguity — envelope key order `meta`/`response_type`/`data`, request-stamp keys before pagination keys — `app.py:46`, `envelope.py:25,33,38`
- §2.2 — revise — **mismatch** — error envelope covers 4xx **and 5xx** (was "4xx status codes") — `app.py:65-67`
- §2.2 — insert — ambiguity — `message` wording is not contractual — `errors.py:97-115`
- §2.2 — insert — ambiguity — unrouted path **and** undeclared method both give `ERR_NOT_FOUND`/**404** (not 405), decided by routing before header checks; unexpected failure gives `ERR_INTERNAL`/500 in the same envelope; trailing slash insignificant — `app.py:45,55-67`
- §2.3 — revise — ambiguity — `limit`/`offset` are trimmed and parsed as whole numbers (fractional/non-numeric/empty -> `ERR_INVALID_PAGINATION`); out-of-range `offset` is not an error — `validate.py:176-196`
- §2.3 — revise — ambiguity — `created_at` ties broken by ascending creation sequence (total order, applied before offset/limit); `has_more` is exactly `offset + rows_returned < total_count`, so a past-the-end page reports false — `resolve.py:54-66`, `core.py:55-57`
- §2.3 — insert — ambiguity — filter semantics: param named like the field, plain case-sensitive equality, out-of-enum value matches nothing rather than 400, integer filters must parse, `overdue_flag` treats literal `true` (any case) as true, conjunctive, unknown params ignored — `resolve.py:69-76`, `routes/assets.py:60-71`, `routes/remediations.py:80-83`
- §2.4 — insert — ambiguity — server-stamped instants always canonical `...sssZ` with finer precision **truncated**; client-supplied instants (`last_tested_at`, engagement/target/training `window_*`, `clearance_expires_at`, `interval_*`) echoed back **verbatim**, normalised value used only internally — `serialize.py:12-16`, `util.py:31-36`
- §2.4 — insert — ambiguity — exact accepted ISO-8601 input forms (`Z`/`z`, `+/-HH:MM`, naive=UTC, space separator, omitted seconds/time, any fractional length) and that unparsable values are `ERR_INVALID_REQUEST` — `util.py:13-28`, `validate.py:121-131`
- §2.4 — insert — ambiguity — declared field set is fixed and unset values render as JSON `null`, never omitted; request-only inputs never surface — `serialize.py:19-25`
- §2.4 — insert — ambiguity — `version` advances once **per request**, not per write, even under re-touching cascades — `core.py:24-32`
- §2.5 — revise — ambiguity — `to_iso8601` mandatory, parsed per §2.4, clock set exactly (sub-second precision retained), may move backwards, responds 200 / `"object"` / empty `data` — `routes/clock.py:12-18`
- §2.6 — insert — ambiguity — numbers rendered as JSON numbers in shortest exact decimal form (12.50 -> `12.5`, 30.00 -> `30.0`); integer fields as plain integers — `util.py:59-63`
- §2.8 Band 1 — insert — ambiguity — action-level role reservations (TERMINATE, RISK_ACCEPT/REVOKE, REPORT/CLOSE) raise `ERR_UNAUTHORIZED`/403 immediately after the action selector is validated, before remaining body fields and all state preconditions — `auth.py:40-43`, `routes/engagements.py:105,143`, `routes/findings.py:147`
- §2.8 Band 2 — insert — **mismatch** — added `ERR_TRAINING_RECOMMENDATION_NOT_FOUND` to the path-resolution error list — `resolve.py:25,51`, `routes/plans.py:166-169`
- §2.8 Band 3 — insert — ambiguity — absent/empty body reads as `{}`; unparsable or non-object body is `ERR_INVALID_REQUEST`; explicit `null` counts as absent; bool/int/number/string/decimal-place type rules; first violation ends the request — `validate.py:21-131`
- §4 preamble — revise — ambiguity — trend-analysis POST returns 201 with `response_type "array"` (possibly empty) and **no** pagination keys in `meta`; clock POST returns 200 with empty object — `routes/plans.py:150`, `routes/clock.py:18`
- §5 — insert — **mismatch** — added the three catalogued-but-undocumented ids: `ERR_TRAINING_RECOMMENDATION_NOT_FOUND` 404, `ERR_NOT_FOUND` 404, `ERR_INTERNAL` 500 (catalogue now matches `ERROR_STATUS` exactly, and all 75 pre-existing rows already matched impl statuses) — `errors.py:23,24,94`

Pass 1 also cross-checked every serializer field name against the PRD across all 14 entities: no impl response field is unnamed by the PRD and no PRD-named response field is missing from impl; the only backticked §3 tokens absent from `serialize.py` are request-only inputs (`action`, `decision`, `result`, `reason`, `note`, `override_note`, `resume_note`, `signature_note`, `stop_code`, `additional_days`, `expected_*`).

Deliberately left unpinned by Pass 1: intra-`data` key order (envelope-level order pinned instead; not a meaningful contract); `request.get_json` content-type framing; store-empty-at-boot (not a PRD interpretation question); `ApiError`'s 400 default for an uncatalogued id (unreachable); `ceil_hours`/`floor_div_days` negative-input flooring (only observable through `calc.py`, deferred to Pass 2).

### Pass 2 report (calc/core + early routes)

File state: 497 lines / 114,480 chars -> 497 lines / 118,244 chars. All edits in-paragraph; section count still 25; tail intact (§5 still ends at `ERR_INTERNAL | 500`). All seven probed Pass-1 marker hunks verified present.

Counts: **ambiguity-pins 9, mismatch-revisions 5** (14 changes across 13 `Edit` calls).

- §3.1 — insert — ambiguity — certification replacement carries no state precondition (a `PENDING_CLEARANCE`/`SUSPENDED` tester is rescored the same) and touches only the tester's own `version` — `routes/testers.py:97-106`
- §3.2 — revise — **mismatch** — "discards the fractional part" now pinned as floor **toward negative infinity** (not truncation toward zero) with no clamp at 0, so a future `last_tested_at` yields a negative staleness contribution — `calc.py:112-121`, `util.py:66-69`
- §3.2 — insert — ambiguity — `requested_engagement_hours` has no decimal-place restriction (unlike `exposure_score`/`technical_base_score`) — `routes/scope.py:28-30`
- §3.2 — insert — ambiguity — fourth tie-break after `priority_score`/hours/`created_at` is creation sequence — `core.py:161-168`
- §3.2 — insert — **mismatch** — a candidate renumbered only because a sibling entered/left the ranked population gets the new `priority_rank` **without** its `version`/`updated_at` advancing (contradicted §2.4's blanket "every mutated record advances") — `core.py:153-171`
- §3.2 — insert — ambiguity — naming the mode already in force is not rejected and is not a no-op; it rescores, re-ranks and advances versions — `routes/plans.py:71-86`
- §3.3 — revise — **mismatch** — only an absent/`null` `override_note` yields `ERR_BELOW_RISK_THRESHOLD`; a present-but-blank one is a band-3 `ERR_INVALID_REQUEST`/400 (as is a blank optional `note`) — `routes/scope.py:84-94`, `validate.py:41-53`
- §3.3 — insert — ambiguity — `override_note`-over-`note` precedence applies to all three decisions, withdrawal records the note too, `decision_note` null when neither given, and every decision recomputes coverage and bumps the plan `version` — `routes/scope.py:102-106`
- §3.3 — insert — **mismatch** — activation is the one write whose body is never parsed, so §2.8's body-shape band inspects nothing (even unparsable payloads activate) — `routes/plans.py:89-104`
- §3.5 — insert — **mismatch** — the tester-side effects are provisioned-only: revoking a `REQUESTED` grant leaves the tester row wholly untouched (counter, `availability_state`, `updated_at`, `version`); the `-> AVAILABLE` move fires only out of `ASSIGNED` — `core.py:237-262`
- §3.9 — insert — ambiguity — an already-`EXCLUDED` target is also moved to `SUSPENDED`, and `active_target_count` is forced to exactly 0 rather than decremented per target — `core.py:314-332`
- §3.9 — insert — ambiguity — `window_start`/`window_end` are validated only as parsable instants; the end need **not** follow the start and a reversed window admits no finding — `routes/plans.py:113-114`
- §3.9 — insert — ambiguity — remaining `discovered_at`/`created_at` tie settled by creation sequence — `routes/plans.py:131`
- §3.9 — insert — ambiguity — score-desc/theme-asc governs the creation response only; records are **persisted** in §3.6's theme declaration order, which (single shared `created_at`) is what the listing read returns — `routes/plans.py:127,147-149`

Pass 2 verified as already uniquely pinned (no change): tier/regime/exposure weights and both mode weight sets; `q2` half-up once at end; coverage numerator/denominator and the empty-inventory 100.00; severity multiplier-then-additive-bonus with clamp-before-round; band thresholds 9/7/4; SEVERITY_POINTS; ack deadlines 60/240/240; SLA defaults and regime caps with min-of; `days_late` floor at 0; `is_overdue` strictness and VALIDATED/CLOSED exemption; `settled_hours` baseline/effective-end/ceil/cap; qualification 45/35/25/15 cap 100 and the 60 lead floor; cooldown 0/12/24; both assurance variants incl. floor/cap and the 5-per-closure/20 credit; training severity weights, 90-day/0.60/0.40 decay, round-before-sum then cap-then-round, MANDATORY at >=3 and >=8.00; all posture transitions and `last_cleared_at`; pause/resume link sets and skip rules; bubble-up condition; band-3 field orders in all six partition endpoints.

Deliberately left unpinned by Pass 2: `recency_multiplier` above 1.0 (reachable only after a backwards clock move; formula + 0.40 floor already uniquely derive it); score-style fields rendering `45.0` rather than `45` (§2.6's Pass-1 hunk covers it); `max(0, ...)` counter clamps (unreachable in any legal sequence); `core.roe_of_engagement`'s revoked-document fallback (unobservable); the general blank-optional-string rule (Pass 1 territory — pinned the observable consequence locally in §3.3 instead).

### Pass 3 report (remaining routes)

File state: 497 lines / 118,244 chars -> 497 lines / 123,351 chars. All 22 hunks in-paragraph; no new lines, sections or paragraphs; file still ends with the §5 catalogue; probed Pass 1/Pass 2 markers intact.

Counts: **ambiguity-pins 16, mismatch-revisions 6.**

Mismatch-revisions:
- §2.6 — revise — **mismatch** — "hour-ledger fields themselves carry at most 2 decimals" was false for the client-supplied allocation; now pins that `hours_reserved`/`hours_consumed`/`hours_available` are quantized as they move while `hours_allocated` and `requested_hours` declare no decimal limit and are stored verbatim (so a fresh charter reports a 3-decimal allocation and opening available verbatim) — `routes/engagements.py:40,59,62`, `routes/assignments.py:43`, `core.py:229`
- §3.4 — revise — **mismatch** — §2.8's blanket "arrays free of duplicate members" contradicted `exclusions`; now pins `exclusions` as the one array that is neither duplicate-checked nor member-length-checked — `routes/roe.py:37`
- §3.5 — revise — **mismatch** — prose had provisioning check the assignment state before the engagement state; reordered to engagement-state-then-assignment-state — `routes/assignments.py:119-128`
- §3.6 — revise — **mismatch** — "a `ComplianceOfficer` may acknowledge a second time" -> either authorized role may (no action-level reservation exists) — `routes/alerts.py:38,42`
- §3.8 — revise — **mismatch** — a present-but-blank `residual_note` is band-3 `ERR_INVALID_REQUEST`/400, not `ERR_RESIDUAL_NOTE_REQUIRED`/422; only omitted/null yields 422 — `routes/retests.py:35,45-47`
- §3.8 — revise — **mismatch** — `REJECTED`, `PARTIALLY_VALIDATED` and `RETEST_FAILED` are never written; pins that no response or later read ever shows them, and trimmed the loop sentence accordingly — `routes/retests.py:69-79`

Ambiguity-pins:
- §3.4 — insert — ambiguity — drafting consults neither engagement axis (suspended/terminated/closed engagements accept a fresh draft) — `routes/roe.py:33-46`
- §3.4 — insert — ambiguity — `signature_note` validated when supplied, persisted nowhere — `routes/roe.py:86`
- §3.4 — insert — ambiguity — signing only flips the engagement when it stands at `ROE_PENDING`; otherwise the engagement row is untouched (state, `updated_at`, `version`) — `routes/roe.py:98-101`
- §3.5 — insert — ambiguity — booking consults neither engagement axis; the four gates are the whole admission test — `routes/assignments.py:50-71`
- §3.5 — insert — ambiguity — an empty `granted_asset_ids` satisfies the subset test and provisions even with no active target — `routes/assignments.py:142`
- §3.6 — insert — ambiguity — with several provisioned assignments for the tester, only the earliest-created one's grant is consulted, so `ERR_ASSET_NOT_GRANTED` still fires when a later one grants the asset — `routes/findings.py:62-70`
- §3.6 — insert — ambiguity — a second acknowledgement leaves `acknowledged_at`/`acknowledged_by_user_id` at their first-ack values — `routes/alerts.py:55-58`
- §3.7 — insert — ambiguity — triage `note` persisted nowhere; the conditional `note`/`duplicate_of_finding_id` requirements are band-3 400s; `duplicate_of_finding_id` is resolved for *every* action, so a bogus id with `ACCEPT`/`RISK_ACCEPT`/`REVOKE_RISK_ACCEPTANCE` is a 404 — `routes/findings.py:148-150`
- §3.7 — insert — ambiguity — the duplicate-marking alert move leaves `acknowledged_at`/`acknowledged_by_user_id` null and touches no `ESCALATED`/`ACKNOWLEDGED` alert — `routes/findings.py:179-183`
- §3.7 — insert — ambiguity — any finding may be the duplicate parent (any engagement/asset/status) and the parent is not modified — `routes/findings.py:160-173`
- §3.7 — insert — ambiguity — `RISK_ACCEPT`/`REVOKE_RISK_ACCEPTANCE` touch no alert, so a `RAISED` alert keeps blocking fieldwork-complete/close — `routes/findings.py:184-197`
- §3.8 — insert — ambiguity — `additional_days` is an integer >= 1 with no upper bound; extension `reason` persisted nowhere — `routes/remediations.py:117-118`
- §3.8 — insert — ambiguity — submit's `evidence_uri` has no declared maximum length (unlike the retest's 1–500) — `routes/remediations.py:92`
- §3.8 — insert — ambiguity — `residual_note` stored verbatim, no max length, null only on a `PASS` — `routes/retests.py:35,54`
- §3.9 — insert — ambiguity — `PAUSE` on an already-`SUSPENDED` engagement is `ERR_ENGAGEMENT_SUSPENDED`, not a no-op; `TERMINATE` accepts either — `routes/engagements.py:147-149`
- §3.9 — insert — ambiguity — `resume_note` validated when supplied, persisted nowhere — `routes/engagements.py:161`

Deliberately left unpinned by Pass 3: `roe_of_engagement`'s revoked-document fallback and `live_roe`'s earliest-live pick (unreachable — reporting requires `AUTHORIZED`, implying a live `SIGNED` document, and band-7 uniqueness permits one live document); the unreachable `residual_note.strip()` branch at `routes/retests.py:46`; `ERR_NO_AUTHORIZED_TARGETS` reading the maintained `active_target_count` instead of rescanning (observationally equivalent); absent maximum lengths on `containment_action`, `closure_note`, triage `note`, exclusion/stop `reason` (§2.8 band 3 already establishes "no bound unless declared"); the wire `overdue_flag` recomputed live at serialization while the stored field refreshes on extension (already consistent with §3.8's live definition and §2.3's filter rule).

Pass 3's closing statement: to the best of its audit, every behavior in its partition now traces to a sentence in `PRD_COMPLETED.md`, with the five unpinned items being unreachable, observationally equivalent, or already covered by an existing general rule.

### Step 9 totals and orchestrator verification

- Source `PRD_FINALIZED.md` 484 lines / 105,049 chars -> `PRD_COMPLETED.md` **497 lines / 123,351 chars** (+13 lines, +18,302 chars, +17.4%).
- **Ambiguity-pins 43, mismatch-revisions 14 — 57 changes total** across the three passes.
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (the failure signature of a scan that never ran); `diff` reports 44 changed hunks.
- `tail -4` shows the file still ends with complete `| ERR_* | NNN |` rows of the §5 catalogue (now closing on `ERR_INTERNAL | 500`) — tail intact, no truncation across three sequential editing passes.
- Leak grep for `scaffold|difficulty|benchmark` over `PRD_COMPLETED.md`: 0 hits. Neither `SCAFFOLD*.yaml` nor `worklog.md` was readable to any Step 9 pass.
- `find workspace/implementation -name '*.py' -newer workspace/PRD_FINALIZED.md` is empty — Steps 8 and 9 modified no implementation file, so Step 7's green state still describes the shipped code.

### Final confirmation sweep (orchestrator-run, post-Step-9)

Because Steps 8–9 are PRD-only, the orchestrator re-ran the full 8-round `setsid nohup` sweep against the as-shipped artifact to verify the delivered state rather than inferring it:

```
round 1: 148 / 148 failed= 0
round 2: 148 / 148 failed= 0
round 3: 148 / 148 failed= 0
round 4: 148 / 148 failed= 0
round 5: 148 / 148 failed= 0
round 6: 148 / 148 failed= 0
round 7: 148 / 148 failed= 0
round 8: 148 / 148 failed= 0
```

Pipeline complete. `workspace/PRD_COMPLETED.md` written; all nine steps recorded above.

# Worklog — task_2391_neurodiagnostic_long_term_eeg_monitoring

## Step 1: Create task directory — 2026-09-02T05:57:16.930Z

Created `tasks/task_2391_neurodiagnostic_long_term_eeg_monitoring/` and `tasks/task_2391_neurodiagnostic_long_term_eeg_monitoring/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T07:36:00.000Z

All three artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2391_neurodiagnostic_long_term_eeg_monitoring/`.

**`SCAFFOLD.yaml`** (§1.0–§1.7, no design keys) — `api_prefix: /neurodiagnostics`
- 15 entities: MonitoringUnit, Bed, Patient, AuthorizationRequest, Admission, TaperPlan, TechnologistShift, Study, SeizureAlert, SafetyIntervention, EventMarking, ReviewReport, ExportPackage, SurgicalConferenceCase, ConferenceVote
- 10 state machines (parallel-shape: Study carries independent `acquisition_state` × `data_state`; Admission carries `clinical_state`), 9 calculations, 31 validations (priorities 1–31), 58 error codes, 71 endpoints + `POST /_clock/set_current_utc`, 5 roles (UnitCoordinator, Technologist, Nurse, Epileptologist, PayerReviewer, segregation_of_duties role model), 2 optimistic-concurrency rules (`admission-extension-stale` → ERR_STALE_ADMISSION_VERSION 412, `export-create-stale-study` → ERR_STALE_STUDY_VERSION 412)
- `difficulty_band: "beyond Expert"`; complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; consistency model immediate

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8) — 23 instances across all nine difficulty rules (2/3/3/2/3/3/3/2/2), every rule ≥2.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9) — 78 instances over the nine claim-extraction sections: 57 with full `test_recipe`, 21 `excluded_because` stubs that defer to named §1.8 instances (all references resolve; no name collides across the two design files).
- entities 13, state_machines 15 (8 full), calculations 13 (5 full), validations 15 (14 full), endpoints 5 (4 full), errors 4, rbac 5, cross_cutting_complexity_layers 7 (3 full), consistency_model 1

**Lint:** `scaffold_lint.py` reports `VERDICT: clean lint` over 1280 scanned calls (71 endpoints, 15 entities, 23 §1.8 + 57 §1.9 recipes), with all FK reverse-reachability satisfied. Temp part files removed.

Design notes worth carrying forward: every corner literal was derived from the pinned constants (32ch INPATIENT = 0.032 GB/min, 24ch AMBULATORY = 0.0096 GB/min, per-segment rounding, export video divisor 2.5, STORAGE_LOCK_PCT 90.00 inclusive, IMPEDANCE_LIMIT_KOHM 10.00, alert deadline nested clamp [2,15], 30-day retention). Four design defects found and fixed during authoring: a duplicated shift-window validation, an unreachable ERR_TAPER_ALREADY_COMPLETE (deleted, 59→58 errors), a NULL-comparison hole in the setting-match rule at priority 13, and a missing tally-retention side effect on PRESENTED→DEFERRED.

## Step 3: Copy shared files — 2026-09-02T07:38:03.657Z

Copied `INSTRUCTION.md` → `tasks/task_2391_neurodiagnostic_long_term_eeg_monitoring/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:53:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — **446 lines**, 26 headings, ends at §5 with no audit footer.

**Sections**
- §1 Introduction (3 paragraphs: EMU business context, scope, the two engineering constraints — logical clock and immediate reconciliation)
- §2 Global Specifications, 11 subsections: 2.1 Operators, Headers and Role Authority (all five roles `identity: opaque`, both segregation-of-duties rules) · 2.2 API Response Structure (verbatim block, byte-identical — verified) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Record Properties (incl. the two reduced-preamble record types) · 2.6 Rejection Precedence: the full 31-rung ladder · 2.7 Optimistic Concurrency on Extension Decisions and Export Creation · 2.8 Numeric Precision, Rounding and Truncation Discipline · 2.9 Parallel State Dimensions, Cascades and Compensations · 2.10 Path Resolution Order for Nested Reads · 2.11 Storage Pressure and the Unit Gating Posture
- §3 Business Logic, 9 subsections: 3.1 unit/bed/coverage setup · 3.2 payer authorization + day ledger · 3.3 admission, bed occupancy, discharge settlement · 3.4 medication-reduction protocol · 3.5 acquisition, segments, electrode maintenance · 3.6 detection, bedside response, triage adjudication · 3.7 marking, capture adequacy, LOS decision · 3.8 interpretation, addenda, turnaround · 3.9 data residency, export, retention, surgical candidacy
- §4 Endpoint Definitions — 71-row, 4-column table
- §5 Error Code Catalogue — 58-row, 2-column table

**Hard Contract audits (all machine-verified against SCAFFOLD.yaml)**

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].input identifiers: 66 required, 66 present, 0 missing
- concurrency_rules[].occ_field: 2 required, 2 present, 0 missing
- union total: 141 required, 141 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose in ladder order, 0 missing
- validations[] error_ids: 58 checked, 58 named in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 59 checked across 10 machines, 59 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (pinned rounding order, pinned S1..S7, pinned posture precedence, pinned T1..T5), 0 missing
- endpoints[].side_effects: 47 endpoints with side effects checked, all expressed, 0 missing
- endpoints[].roles: 71 checked, 71 match the §4 table exactly, 0 mismatches
- errors[] HTTP codes: 58 checked, 58 match scaffold, 0 mismatches
- sibling-branch symmetry: 6 groups checked (CLINICAL/SUBCLINICAL/ARTIFACT adjudication; complete-from-ACQUIRING vs from-PAUSED; retrospective vs prospective adequacy; calendar vs coverage turnaround; include_video true/false; the two blocked_reason literals), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 973
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- tokens containing `/` at all: 0
Status: PASS
```

Additional scans: zero pseudocode operators anywhere in the document (`>=`, `<=`, `+=`, `==`, `->`, `min(`, `ceil(`, `floor(`, bare `AND`/`OR`/`IN`/`NULL`/`TRUE`/`FALSE`) — all translated to prose; no fuzzy/approximating qualifiers on any requirement.

Constraint compliance: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read. Note that SCAFFOLD.yaml itself carries one inline worked-example number set for the storage rounding-order pin; I expressed the *rule* (round per segment, re-round after each accumulation) without transcribing those figures.

## Step 5: Generate unit tests — 2026-09-02T08:35:00.000Z

Generation and verification are complete for `/home/ubuntu/github/CodingPRD/tasks/task_2391_neurodiagnostic_long_term_eeg_monitoring/`.

**Stage 1 — `test_helpers/` (9 files)**
`__init__.py` (re-exports framework validators + local assertions; registers the error→status map on import), `constants.py` (routing, clock literals, all enum values, precision and formula constants: `TURNOVER_BUFFER_MINUTES=90`, `GB_PER_CHANNEL_MINUTE=0.0004`, `MODALITY_FACTOR`, `STORAGE_LOCK_PCT=90.00`, `CLASS_WEIGHT`, `TAPER_PROVOKED_DISCOUNT=0.75`, tier deadlines, `RISK_ALLOWANCE_UNITS=24`, `RETENTION_DAYS=30`, quorum constants), `api_errors.py` (all 58 error ids + `ERROR_HTTP_STATUS`), `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD §4 endpoint plus `set_clock` and `raw`), `types.py` (TypedDicts; append-only evidence — safety interventions and conference votes — deliberately expose only `id`/`created_at`), `factories.py` (28 payload builders; `None` prunes a field so defaults are exercised), `assertions.py` (three numeric precisions, instant equality, full vs append-only preamble, conserved day-ledger equality, paired state dimensions, case tallies), `fixtures.py` (five tiers of endpoint-built preconditions + `Baseline` dataclass + `build_admitted_stay`/`build_acquiring_stay` composites), `test_users.py` (five roles + negative-auth header sets).

**Stage 2 — `test_suite/` (`conftest.py` + 17 test files, 105 tests)**
- Queue A (Difficulty): **48 tests / 23 instances / 9 rule_ids**, every instance ≥2 tests — `test_01` dual_variant_calc (4), `test_02` combinatorial_formula (6), `test_03` non_linear_state_machine (6), `test_04` transitive_cascade (4), `test_05` priority_pair_validation_conflict (6), `test_06` boundary_precision_check (7), `test_07` cross_entity_state_dependency (6), `test_08` resource_temporal_overlap (5), `test_09` compensating_invariant (4).
- Queue B (Corner): **57 tests / 57 non-stub instances / 9 sections**, 1 each — `test_10` entities (13), `test_11` state_machines (8), `test_12` calculations (5), `test_13` validations (14), `test_14` endpoints (4), `test_15` errors (4), `test_16` rbac (5), `test_17` cross_cutting + consistency_model (4). The 21 corner `excluded_because:` stubs were not translated.

**Coverage audit** (AST + regex against an authoritative 80-tag list extracted from the two YAMLs with PyYAML): tests parsed 105; uncovered design instances 0; difficulty instances with <2 tests none; tag problems 0 (exactly one `Design:` line per docstring, always the final line, no unknown/dual tags); non-verbatim quotes 0 (every quoted span ≥40 chars is a verbatim PRD substring after whitespace normalization). `pytest test_suite --collect-only -q` → 105 collected, no errors. Hygiene greps: no skip/xfail markers, no mocking, no scaffold/design-document leakage. A static pass also confirmed every `api.*` and helper-module attribute referenced by the suite exists (0 bad references).

**Skipped instances: none** — all 23 difficulty and all 57 non-stub corner instances passed the PRD-first two-condition filter.

Notable PRD-derived resolutions worth recording: prospective capture adequacy is recomputed from post-grant `days_available` (0.750); the taper-plan lifecycle field is unnamed in the PRD, so a local `_taper_plan_state()` reader accepts `status` or `state`; bed `released_at`/`turnover_clear_at` are asserted only immediately post-discharge (PRD silent on re-admit clearing); 404 probes use `NON_EXISTENT_UUID` because ladder rung 3 (400) precedes rung 4 (404); PRD-silent computed fields (`active_study_count`, `coverage_capacity`) were replaced with the shift's `assigned_study_count`, which per §3.1 is not decremented by a pause — that is what makes the capacity-vs-storage-lock precedence pair reachable.

## Step 6: Generate implementation — 2026-09-02T09:16:22.448Z

Implementation is complete and passing its full self-check.

## Files written
All under `workspace/implementation/` — 21 files, ~3,400 lines:

**Launcher / infra**
- `start.sh` — `exec python3 serve.py`
- `serve.py` — in-process Flask-availability check (pip-installs only when missing), then `app.run(host=0.0.0.0, port=$PORT, threaded=True, use_reloader=False)`
- `requirements.txt` — `flask>=2.0`
- `app.py` — app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers emitting the error envelope

**Core**
- `config.py` (all enums + numeric constants), `clock.py` (logical UTC clock pinned to `2026-08-01T00:00:00Z`, monotonic), `db.py` (15 in-memory collections, `base_record`, reduced preamble for interventions/votes), `errors.py` (58-code `ERROR_HTTP` map), `response.py` (envelope, `req_` + 20-alnum request ids, pagination meta), `auth.py` (rungs 1–2), `validation.py` (rungs 3–4), `derive.py` (809 lines — all computed fields, Decimal ROUND_HALF_UP, floor/ceil rules, unit posture and storage figures), `cascade.py` (diff-based version bumping + edge-triggered posture cascade), `web.py` (endpoint decorator, FK lookups, global request lock)

**Routes — 71 endpoints total**
`routes_admission.py` 13 · `routes_event.py` 12 · `routes_infrastructure.py` 11 (incl. `/_clock/set_current_utc`) · `routes_report.py` 11 · `routes_study.py` 10 · `routes_authorization.py` 7 · `routes_conference.py` 7

## Verification
- `app.url_map` reports exactly **71** routes, matching the PRD §5 endpoint table.
- Cold boot: 0 records in all 15 collections, clock reads `2026-08-01T00:00:00.000Z`. No file/DB persistence anywhere (only `json.dumps` for in-memory fingerprinting); no seeding, preloading or hardcoded entities.
- End-to-end self-check (`/tmp/emu_check.py`, not part of the deliverable): **141 assertions, ALL CHECKS PASSED** against a freshly booted server — envelope shape, auth rungs, every reachable ladder error, and all computed figures across the full nine-workflow path (unit/bed/shift → authorization → admission → study capture → alerts/interventions/markings → reports → exports → conference).
- Per-test-server reboot verified twice on clean ports: healthy response ~3.9 s after `start.sh` on a host at load average 250. Moving the dependency probe into `serve.py` (one interpreter launch instead of two) halved boot time from ~8 s, which matters because the harness relaunches before every test.

## Notes for the worklog
- Ladder-vs-prose conflicts were resolved in favour of the numbered ladder per PRD §2.6 ("nothing later may mask something earlier"): study start evaluates rung 11/12 tech coverage before rung 13 `ERR_SETTING_MISMATCH`; extension evaluates rung 26 `ERR_NO_YIELD_BASIS` before rung 27 `ERR_TARGET_ALREADY_MET`; discharge evaluates rung 6 before rung 29.
- `DENIED_TARGET_MET` is a declared-but-unreachable extension outcome (rung 27 refuses first) — implemented as such deliberately.
- Pinned interpretation: `unit_storage_used_gb` sums `stored_gb` of ONLINE/EXPORT_HELD studies **plus** `package_gb` of BUILT/DELIVERED packages *on those same studies*, so archiving a study also drops its delivered package's volume (SCAFFOLD `unit_storage_pressure` formula + PRD §2.11).
- Constraints honoured: nothing under `test_helpers/` or `test_suite/` was read or listed, no `SCAFFOLD_*_DESIGN.yaml` was opened, and no sibling task directory was inspected. Also removed a stray empty `routes/` directory and `__pycache__` from the implementation dir.

*(Orchestrator note: Steps 5 and 6 ran sequentially rather than concurrently. Physical isolation was preserved by hard constraint instead — the impl-gen subagent was explicitly forbidden from reading `test_helpers/` and `test_suite/`, and confirmed compliance.)*

## Step 7: Run tests and iterate to green — 2026-09-02T10:25:00.000Z

Diagnostic loop over `test_suite/`, `test_helpers/` and `workspace/implementation/`.

**Real defects found — 2, both test bugs, both fixed in `test_suite/` (no implementation change, no deletion):**

1. `test_04_adjudication_and_export_cascades.py` — helper `_stay_with_two_attended_clinical_markings` returned the alert snapshot taken at *creation* (version 1) and the test then asserted `adjudicated["version"] == alert["version"] + 1`. Between those two points the fixture records the first safety intervention, which per PRD §3.6 ("Either way the alert's `version` increments by 1.") is itself a mutation of the alert, so the observed version was 3. Fixed by re-reading the alert after the intervention so the snapshot is the state immediately before adjudication. Failed 8/8 rounds before the fix.

2. `test_08_bed_and_coverage_overlap.py::test_readmission_refused_one_minute_before_the_turnover_buffer_clears` — asserted `AUTH_STATE_ACTIVE` on the *waiting* admission after its admit was refused with `ERR_BED_OCCUPANCY_CONFLICT`. PRD §3.3: "The new record opens with `clinical_state` at `SCHEDULED` and `authorization_state` at `AUTH_PENDING`", and only a successful admit "moves `authorization_state` from `AUTH_PENDING` to `AUTH_ACTIVE`". Corrected to `AUTH_STATE_PENDING`. Failed 7/8 rounds before the fix.

No test was deleted (no STEP-1 PRD-silence or unique-derivability collapse was reached), and `workspace/implementation/` was not modified.

**Verification**

- Three independent full-suite repetitions with one freshly booted server per test (own harness, `ss`-based port handling, no `lsof`): **105/105 passed each time — 315/315 test executions, zero failures.**
- Three 8-round parallel `prd-bench-local-run` sweeps (24 rounds, 2520 test executions): **`failed == 0` in every round.** All non-passes were setup errors of one single kind:
  `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...)' timed out after 5 seconds"`
  i.e. the runner's own 5-second `lsof` port-probe in `pytest_plugin._kill_port`, not the artifact.
- Union check over the last full sweep: all 105 distinct tests passed in at least 3 of the 8 rounds; **0 tests ever recorded an assertion failure in any round.**

**Host context.** The sweeps ran on a shared farm carrying ~65 other concurrent task pipelines, ~2,900 processes and a load average of 240–380. Measured `lsof -ti:<port> -sTCP:LISTEN` latency in that state was 0.9 s–6.7 s, with roughly a quarter of probes exceeding the runner's hard-coded `timeout=5`; with `--isolation per-test-server` that probe runs once per test, so 105 tests x 8 rounds yields a few hundred spurious setup errors regardless of the artifact. This is the documented host behaviour for this runner. A fully green official sweep is therefore gated on host quiesce, not on anything left in this task directory.

## Step 8: Finalize PRD — 2026-09-02T10:33:00.000Z

**Result: `PRD_FINALIZED.md` created on disk and is byte-identical to `PRD.md`. No edits were warranted.**

- Line counts: PRD.md 445 / PRD_FINALIZED.md 445 — 0 changed lines, **0.0% delta**.
- Change bullets: none.

## Why no edits

Both `<step_7_diff>` items were pure fixture bugs on behavior the PRD already determines uniquely; neither revealed PRD-silence nor a PRD/impl mismatch.

**Item 1 — alert `version` snapshot (`test_04`).** Subject: when the alert record's `version` moves across the intervention → adjudication sequence.
- Paths enumerated/read: `implementation/routes_event.py:128-163` (`create_intervention`, `first`-gated response settlement), `:71-104` (`adjudicate_alert`, all three classification branches + marking cascade), `:107-123` (`close_alert`), `implementation/cascade.py:19-66` (`begin_request`/`_fingerprint`/`finalize` — versioning is fingerprint-diff based, `version += 1` exactly once per request per record whose rendering changed; `force_bump` for invisible mutations), `cascade.py:109-133` (capture reconciliation), `implementation/db.py:58-70` (new records open at `version` 1).
- Finding: alert created at v1; the first intervention changes `responded_at`/`latency_minutes`/`response_state`, so `finalize()` bumps it to v2 (exactly PRD §3.6 "Either way the alert's `version` increments by 1"); adjudication bumps it to v3 (PRD §3.6 "The alert's own `version` increments by 1"). The observed 3 is what the PRD prescribes — the test was reading a stale creation-time snapshot. PRD §3.6 lines 236 and 240-244 kept verbatim.
- Wording adjustment: none (no edit). Note: deliberately did *not* add a clause about non-first interventions leaving the alert `version` untouched (which is what the fingerprint scheme yields) — that path was not exercised by the Step 7 fix, so it is out of HARD SCOPE, and pinning it would risk a new mismatch against the generic §2.9/§2.5 version rule.

**Item 2 — `authorization_state` after a refused admit (`test_08`).** Subject: the funding dimension of a `SCHEDULED` admission whose admit was refused, plus the bed turnover boundary the refusal keys on.
- Paths enumerated/read: `implementation/routes_admission.py:40-55` (schedule opens `clinical_state=SCHEDULED`, `authorization_state=AUTH_PENDING`), `:100-152` (admit ladder rungs 6/13/14/15/19/20/21 in exactly the PRD §3.3 order; `AUTH_ACTIVE` and the ledger reservation are set only after every rung passes), `:197` and surrounding discharge/settlement (`AUTH_ACTIVE`→`AUTH_CLOSED`, `AUTH_EXHAUSTED` path), `:239` (`turnover_clear_at = released_at + 90 min`), `derive.py:291-303` (`bed_status`: `OCCUPIED` → `TURNOVER` while `clock.now() < turnover_clear_at` → else `AVAILABLE`, i.e. reaching `turnover_clear_at` is inclusive), `implementation/web.py:53-77` + `cascade.py:69-73` (`abort_request` on any raised `ApiError`, so a refused request leaves no state and no version bump), `config.py:24` (state literals are `AUTH_PENDING`/`AUTH_ACTIVE`/…, matching PRD prose; `AUTH_STATE_PENDING` is only a test-helper constant *name*).
- Finding: PRD §3.3 line 190 ("opens with `clinical_state` at `SCHEDULED` and `authorization_state` at `AUTH_PENDING`") and line 194 ("It moves `authorization_state` from `AUTH_PENDING` to `AUTH_ACTIVE`", listed among the on-success effects) already pin this; the half-open turnover exclusion is pinned by §2.6/§3.1 and matches `derive.bed_status` exactly. Test asserted the wrong constant. Kept verbatim.
- Wording adjustment: none (no edit).

## Step 9: Complete PRD — 2026-09-02T10:46:00.000Z

`PRD_COMPLETED.md` is written. All 23 changes are 1:1 in-paragraph line replacements — no new sections, no line-count change.

**Source vs output:** `PRD_FINALIZED.md` 445 lines / 104,277 chars → `PRD_COMPLETED.md` 445 lines / 110,353 chars (**+6,076 chars**, +23 revised lines).

**Counts:** 14 ambiguity-pins, 9 mismatch-revisions.

**Changes**

- §2.1 Operators/Headers — revise — mismatch — blank/whitespace-only `X-User-ID` or `X-User-Role` also yields `ERR_UNAUTHENTICATED`, not just absent headers — `auth.py:14`
- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — `response.py:18`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not host wall time — `response.py:24`
- §2.3 Pagination — insert — mismatch — on nested list endpoints the parent path id is resolved *before* `limit`/`offset` are read, so a bad parent wins over an out-of-range limit — `routes_infrastructure.py:104`
- §2.3 Pagination — insert — ambiguity — equal `created_at` values (common under the logical clock) tie-break on server insertion sequence — `db.py:80`
- §2.4 Logical Clock — insert — ambiguity — advancing the clock mutates no record: no `updated_at`/`version` move and no package block/unblock cascade runs, though derived reads shift — `routes_infrastructure.py:22`
- §2.5 Common Record Properties — insert — mismatch — `version`/`updated_at` move only on *observable* change; an idempotent re-derivation leaves them alone; the study bump on export-create is the one unconditional exception — `cascade.py:60`, `routes_report.py:151`
- §2.8 Numeric Precision — revise — mismatch — `storage_quota_gb` is echoed verbatim as supplied (not re-rounded to 2dp) and divided at full precision — `derive.py:531`
- §3.1 Beds — revise — mismatch — bed `label` uniqueness within a unit is not enforced — `routes_infrastructure.py:84`
- §3.1 Coverage windows — revise — mismatch — naming a `SCHEDULED`/`CLOSED` shift at study start yields `ERR_NO_TECH_COVERAGE`, not `ERR_INVALID_SHIFT_STATE` — `routes_study.py:125`
- §3.2 Patients — revise — mismatch — patient `mrn` uniqueness is not enforced — `routes_authorization.py:16`
- §3.4 Taper plans — insert — ambiguity — with several plans, the *most recently created* `ACTIVE`/`HELD`/`COMPLETED` plan supplies the step (`ABORTED` skipped, else 0) — `derive.py:321`
- §3.4 Hold — insert — ambiguity — a hold imposes no admission `clinical_state` requirement (unlike advance/resume) — `routes_admission.py:326`
- §3.5 Study creation — insert — ambiguity — create imposes no admission-state precondition — `routes_study.py:52`
- §3.5 Start conditions — revise — mismatch — coverage and capacity are evaluated *ahead of* setting agreement (ladder order, not the prose order) — `routes_study.py:124`
- §3.5 Pause maintenance — insert — ambiguity — `maintenance_kind` is free text; impedance records only for literal `ELECTRODE_REGEL` *with* a present `impedance_kohm`, else silently ignored — `routes_study.py:159`
- §3.5 Completion — revise — ambiguity — completing from `PREPARING` is also `ERR_INVALID_STUDY_STATE` — `routes_study.py:190`
- §3.6 Alert raise — insert — ambiguity — no study `acquisition_state`/`data_state` precondition on raising an alert — `routes_event.py:34`
- §3.7 Marking creation — insert — ambiguity — segment containment is inclusive at both endpoints; open segment never qualifies; `alert_id` need not belong to the same study — `derive.py:214`, `routes_event.py:189`
- §3.7 Extension guards — revise — mismatch — refusal order is `ERR_INVALID_ADMISSION_STATE` → version → `ERR_NO_YIELD_BASIS` → `ERR_TARGET_ALREADY_MET`; `SCHEDULED` admissions fall to `ERR_NO_YIELD_BASIS` — `routes_admission.py:164`
- §3.7 Extension outcomes — insert — ambiguity — `DENIED_TARGET_MET` is never written; zero-grant splits `DENIED_RISK` vs `DENIED_AUTH_DAYS` on the risk budget alone — `derive.py:461`
- §3.9 Export release — insert — ambiguity — `export_hold_reason` is retained after release — `routes_study.py:232`
- §3.9 Blocking/unblocking — insert — ambiguity — the storage-lock block/release is edge-triggered within the request, so a package queued against an already-locked unit stays `QUEUED` — `cascade.py:78`

## Orchestrator verification note — 2026-09-02T11:30:00.000Z

Independent post-Step-9 re-verification by the orchestrator was attempted twice and is **inconclusive due to host saturation, not the artifact**:

- 2-round sweep (`--test-timeout 30`): `failed=0` / `failed=1` — the single "failed" was `Failed: Timeout (>30.0s) from pytest-timeout` on `test_alert_deadline_clamps_up_to_floor_at_night`, while *passing* tests in the same round took 18–25 s each. Not an assertion failure.
- 1-round sweep with headroom (`--timeout 300 --test-timeout 180`): abandoned at ~42% when the host load average went from 336 → **12,993** on 32 cores; trivial `python3` invocations stopped completing.

Across the 8 recorded `results.{1..8}.json` rounds of the Step 7 final sweep: **`failed == 0` in every round**; all non-passes are setup errors of the single form `subprocess.TimeoutExpired: ... lsof -ti:<port> -sTCP:LISTEN ... timed out after 5 seconds` — the runner's own hard-coded 5 s port probe in `pytest_plugin._kill_port`, which is the documented failure mode on a loaded host.

Standing evidence of green: the Step 7 subagent ran the full suite three times with per-test fresh servers using an `ss`-based harness that bypasses the `lsof` probe — **105/105 passing each time, 315/315 executions, zero failures** — plus three 8-round `prd-bench-local-run` sweeps (24 rounds, 2,520 executions) with `failed == 0` in every round. A fully green *official* sweep is gated on host quiesce alone.

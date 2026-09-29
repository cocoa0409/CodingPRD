# Worklog — task_2367_inpatient_psychiatric_unit_admission_involuntary

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/` and `workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:56:00.000Z

All three scaffold artifacts for task 2367 are complete and lint-clean.

## Files (all absolute)
- `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD.yaml` (1,654 lines, §1.0–§1.7 only — no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,329 lines, single top-level key)
- `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD_CORNER_DESIGN.yaml` (4,002 lines, single top-level key)

## Scaffold size (above-Expert target)
13 entities · 8 state machines · 2 §1.2.1 OCC rules · 9 calculations (2 dual-variant pairs) · 49 ordered validations · 53 endpoints · 49 errors · 5 roles. Archetypes: compliance_audit + temporal_windowing; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions; topology flat; state shape parallel (Admission legal × placement axes, cyclic petition, branching restraint, compound unit posture); role model segregation_of_duties; consistency immediate.

## Design instances
- §1.8: 9 rule_ids, 19 instances (deadline dual-variant divergence, monitoring grid-vs-raw, bed selector ranking, per-episode ceiling-before-sum, posture reserve ordering, petition continuance cycle, parallel axes, discharge→posture→promotion chain, rescission 4-link cascade, priority-ordering pairs, acuity/follow-up/docket/seclusion boundaries, two conservation invariants).
- §1.9: 9 sections, 66 instances = 45 with full `test_recipe` + 21 `excluded_because` stubs (all cited difficulty_instance names verified to exist). Sections: entities 10, state_machines 21, calculations 9, validations 5, endpoints 3, errors 9, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1.

## Coverage audit
- All 49 error codes are triggered somewhere across §1.8+§1.9 (0 orphans); the last gaps closed this pass were ERR_UNAUTHENTICATED / ERR_UNAUTHORIZED (rbac) and ERR_STALE_UNIT_VERSION / ERR_STALE_ADMISSION_VERSION (both §1.2.1 rules, cross-cutting).
- All 53 endpoints are exercised (0 never-called), no calls to undeclared endpoints.
- 0 unbound `${...}` placeholders in either design file; 0 forbidden concurrency-vocabulary hits; both design files parse as valid YAML with exactly one top-level key each.
- Fixed while auditing: `search_type` values corrected to the declared enum (VISUAL/WANDED/FULL_BODY_WITH_CONSENT), missing required `wing_code` on 8 bed creations, `ordered_duration_minutes` (not `duration_minutes`), `rescind_reason` (not `rescission_reason`), `licensed_placement_bed_count` field name, `capacity_determination_id` left null for PATIENT_CONSENT, and the SCAFFOLD header comment now says 8 state machines.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  1073

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint was honored throughout: no sibling `task_*/` directory was listed, globbed, grepped, or read — the scaffold derives only from the scenario line and the generator skill's own spec/reference.

## Step 3: Copy shared files — 2026-09-02T05:56:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:09:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/workspace/PRD.md` (430 lines, 87.6 KB). The two withheld design files were never opened, grepped, or referenced.

## Hard Contract PASS reports

**Contract 1 — Field-Name Coverage: PASS.** Mechanically diffed with a script that extracts every backticked token from PRD.md (splitting compound tokens on non-identifier characters) against every name in the scaffold.
- Entity fields: 124 required, 0 missing.
- Request-body inputs: 71 required, 0 missing (includes `expected_unit_version`, `expected_admission_version`, `to_iso8601`, `posture_override_reason`, `requested_legal_status`, `conversion_note`, `rescind_reason`, `withdraw_reason`, all note fields).
- Query parameters: 29 required, 0 missing.
- Enum members: 0 missing across all entity enum fields.
- State names: 0 genuinely missing (the only "misses" reported were the scaffold's composite axis labels such as `placement_status PLACED or DISCHARGE_READY`, whose components are all present).

**Contract 2 — Rule Coverage: PASS.** All 49 validations rendered in §2.9 as an ordered 1–49 precedence ladder whose error-ID sequence is byte-identical to the scaffold's `priority` sort (verified programmatically: `order identical: True`), each with its `applies_to` scope stated in action terms. All 37 transitions across all 8 state machines rendered with preconditions mapped to error IDs and every side-effect chain spelled out link by link (hold certify/rescind/convert/supersede/court-denial/statutory-expiry; petition withdrawal's three distinct shapes; the bounded `HEARING_SCHEDULED → CONTINUED → HEARING_SCHEDULED` cycle; both restraint expiry branches with their differing `released_at` and `actual_duration_minutes`; both discharge-request grant targets; all three posture transitions including `OPEN → RESTRICTED` firing no promotion). Both concurrency rules rendered in §2.7 with the explicit "no other endpoint accepts a version field" statement. All 9 calculations rendered in precise prose with pinned evaluation order and inclusive/exclusive boundaries: per-episode-then-sum ceiling for quarter hours, the 4-step non-circular posture chain, the grid-vs-raw compliance pair with the gating asymmetry, the calendar-clock vs judicial-day deadline pair, the 5-key placement rank tuple, the 3-key promotion ordering, the 24-business-hour deadline, the 30-day recency window, and the minor-capped follow-up window.

**Contract 3 — §3 Path Purity: PASS.** 903 backticked tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path pairs. A raw-text scan (outside backticks too) found 0 occurrences of `GET|POST|PUT|PATCH|DELETE` and 0 occurrences of `/behavioral-health…` anywhere in §3.

## Structure

§1 Introduction; §2.1 RBAC (5 roles, per-role identity translation, `ComplianceOfficer` opaque), §2.2 verbatim fixed block (byte-for-byte match verified), §2.3 Pagination + per-collection filters, §2.4 Logical Clock & Compliance Sweep, §2.5 Common Resource Properties, §2.6 Clocks/Calendars/Precision, §2.7 Version Guards, §2.8 Cascade Discipline, §2.9 Validation Precedence, §2.10 Segregation of Duties, §2.11 Rights Violations; §3.1–§3.8 business logic (roster/inventory, intake & evaluation, hold lifecycle, petitions & court, admission/search/placement, restraint & seclusion, capacity & consent, discharge); §4 endpoint table; §5 error table. File ends at §5 — no PASS report or audit text leaked into the document, and no sibling files were created.

## Coverage audit

| Element | Scaffold | Rendered |
| --- | --- | --- |
| Entities | 13 | 13 (all fields, all enums, all defaults) |
| Endpoints | 53 | 53 rows, 4 columns; method+path set exactly equals scaffold (0 missing, 0 extra) |
| Errors | 49 | 49 rows, 2 columns; same order, all HTTP statuses match scaffold |
| State machines / transitions | 8 / 37 | 8 / 37 |
| Calculations | 9 | 9 |
| Validations | 49 | 49, priority order exact |
| Concurrency rules | 2 | 2 |
| Roles | 5 | 5 |

## Step 5: Generate unit tests — 2026-09-02T07:47:00.000Z

All queues are complete and every audit pass is clean.

## Files written (this session)
- `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/test_suite/test_30_rbac.py` — 4 tests over the 4 `rbac` instances (missing/undeclared identity headers; exclusive-operation refusals ahead of existence checks, including a startup-clock proof that the rejected clock move wrote nothing; the `posture_override_reason` role-scoped field; shared operations across two roles; self-witnessed safety search).
- `.../test_suite/test_31_version_guards_and_sweep.py` — 3 tests over the 2 non-stub `cross_cutting_complexity_layers` instances (2 for both OCC guards, 1 for the sweep's two restraint-expiry branches).
- `.../test_suite/test_32_immediate_consistency.py` — 1 test for the single `consistency_model` instance.

Earlier in the same task: `test_helpers/` (8 modules + `__init__.py`), `test_suite/conftest.py`, and `test_01`–`test_14` (queue A) plus `test_20`–`test_29` (queue B).

## Final counts
- **105 tests collected**, 105 `Design:` tags — exactly one per test, none dual-tagged or untagged.
- **Queue A (Difficulty): 52 tests over 19/19 non-stub instances**, every instance ≥2 tests.
- **Queue B (Corner): 53 tests over 45/45 non-stub instances**, every instance ≥1 test.
- 21 `excluded_because:` stubs correctly left untranslated; no tag points at a stub or a non-existent instance, and every tag's `<section>`/`<rule_id>` matches its source yaml.

## Instances skipped / partially translated
- **Skipped: none.** Every non-stub instance in both indices survived the PRD-first filter.
- **One sub-assertion omitted** (instance still translated): in the corner instance `compliance_sweep_expires_unanswered_discharge_request_and_flags_violation`, the design asserts `placement_status` stays `PENDING_PLACEMENT`, which contradicts PRD §3.8 ("VOLUNTARY `PENDING_PLACEMENT` → `CANCELLED`"). That single assertion was dropped (neither value asserted); every other PRD-derivable assertion in the instance is present.

## Audit passes
- `python3 -m pyflakes test_suite/*.py` — clean.
- Citation check (verbatim contiguous PRD quotes) — **0 failures**; section labels also hand-verified against the PRD heading map (two mislabels found and fixed this session: a §4 endpoint-table citation initially labelled §2.10, and one invented §3.1 bed-status sentence replaced with the real `AVAILABLE / OCCUPIED / BLOCKED_CLEANING / OUT_OF_SERVICE` wording).
- Attribute check — 0 failures; call-signature check — 0 failures.
- Scaffold-leak grep (`scaffold`, `§1.x`, `rule_id`, `distinguishing_aspect`, `test_recipe`) over `test_suite/` and `test_helpers/` — no hits.
- `workspace/implementation/` was never read, listed, or imported.

## Step 6: Generate implementation — 2026-09-02T08:17:00.000Z

Both scratch servers are stopped; cleanup complete. The implementation is finished and verified.

## Files written (20)

Under `/home/ubuntu/github/CodingPRD/tasks/task_2367_inpatient_psychiatric_unit_admission_involuntary/workspace/implementation/`:

- `start.sh`, `requirements.txt` (`flask>=2.2`), `app.py`
- Core: `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validation.py`, `timeutil.py`, `calc.py`, `cascades.py`, `serializers.py`
- Routes: `routes/__init__.py`, `roster.py`, `ops.py`, `evaluations.py`, `holds.py`, `admissions.py`, `restraints.py`, `consents.py`

## Endpoints: 53 / 53

`app.url_map` registers exactly 53 rules, matching the 53 rows of the PRD §4 endpoint table one-for-one (including the deliberate absence of collection listings for clinicians/units/beds/patients — those correctly return 405).

## Implemented behaviour

- **Validations:** all 49 error IDs with the PRD §2.9 numbered precedence list treated as authoritative over narrative §3.x prose (auth → authz → schema → existence → OCC → state → clinical/temporal/capacity).
- **State machines (8):** evaluation, hold (incl. `SUPERSEDED`/`STATUTORY_EXPIRY`/`DISCHARGED_BY_COURT`), petition, hearing (`outcome` stays `PENDING` on continuance — stored enum is only `PENDING|GRANTED|DENIED`), admission's two independent axes (`legal_status` × `placement_status`), restraint episode, discharge request, consent/capacity determination.
- **Concurrency:** `expected_unit_version` → `ERR_STALE_UNIT_VERSION` 412; `expected_admission_version` → `ERR_STALE_ADMISSION_VERSION` 412.
- **Calculations (9):** acuity score/tier, statutory hold deadlines with the dual `calendar_clock` vs `judicial_day_clock` divergence, monitoring compliance in both `interval_grid` (gates debrief) and `raw_count` (never gates) variants with `Decimal`/`ROUND_HALF_UP` to 1dp, per-episode-ceiling-then-sum observation staffing quarter-hours, restraint duration ceiling, the pinned 4-step unit posture/availability chain, the deterministic 5-key bed selector, the 3-key promotion ranking, and business/court-calendar deadlines with the 5 2026 holidays.
- **Storage:** 13 in-memory dicts, empty on every boot — no seeding, preloading or hardcoded entity data anywhere. Logical clock defaults to `2026-08-01T00:00:00Z`; the explicit `/_compliance/sweep` is the only expiry engine (4 families). All requests serialized under a global `RLock`.

## Boot verification

Fresh `bash start.sh` with `PORT=18374`/`18377` came up cleanly; all 9 collection listings returned `200` with `total_count=0` and empty `data`, confirming zero seeded state. `store.COLLECTIONS` all-empty and default-clock assertions pass in-process.

## Smoke testing

104 assertions across four end-to-end suites now pass except for four failures that I traced individually and confirmed to be **test-script setup/expectation errors, not implementation defects**:

- `follow-up window exceeded` — the rescission cascade had already moved the admission to `DISCHARGE_READY`, so `ERR_ADMISSION_NOT_DISCHARGEABLE` was correct.
- `auto select no eligible bed` — the unit was genuinely `RESTRICTED` with effective availability 0, so rule 48 (`ERR_UNIT_POSTURE_BLOCKED`) correctly preempts rule 49.
- `docket conflict at 29m` — the petition was already `HEARING_SCHEDULED`, so rule 18 (`ERR_PETITION_NOT_OPEN`) correctly preempts rule 34. Re-tested against a fresh petition, the 29-minute gap correctly yields `ERR_ADVOCATE_DOCKET_CONFLICT` and a 30-minute gap is accepted.
- The two `A4` assertions — the test unit had run out of eligible beds so the admission was never placed. Re-tested on a properly provisioned unit: rescinding a hold keeps `placement_status=PLACED` while flipping only the legal axis to `VOLUNTARY`, and an unanswered discharge request then produces `rights_violation_flag=true` + `DISCHARGE_READY` and frees the bed. The business-hours response deadline computed as `2026-09-15T09:00:00.000Z` from a `2026-09-10T12:00Z` request, which is exactly 24 business hours across the intervening weekend.

Also independently confirmed: the `GRANTED` petition branch minting an `EXTENSION_14D` successor (`statutory_hours=336`, `clock_started_at` = predecessor's `release_deadline_at`, `certifying_clinician_id` = petitioning clinician) with `active_hold_count` netting to 1; the `DENIED` branch cascading to `DISCHARGED_BY_COURT` → `VOLUNTARY` → `DISCHARGE_READY` → `GRANTED_DISCHARGE`; petition withdrawal vacating the hearing and releasing advocate docket minutes; seclusion capacity enforcement; restraint sweep expiry writing `EXPIRED_UNAUTHORIZED` with `grid_compliance_pct=0.0`; and sweep idempotence.

Note (orchestrator): Steps 5 and 6 ran sequentially rather than concurrently; Step 6 was given an explicit hard-isolation constraint forbidding any read/list/grep of `test_suite/`, `test_helpers/`, and both design YAMLs, so the intended physical isolation was preserved by instruction.

## Step 7: Run tests and iterate — 2026-09-02T13:10:00.000Z

Clean sweep on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1

**Sweep result:** all 8 parallel rounds reported `passed == total == 105`, `failed 0`, `errors 0`. No test failed in any round, so there was no flakiness signal to chase and no union failure set to triage.

- Round 1–8: 105/105 each.

**Tests deleted:** none (no test failed, so no PRD-coverage / unique-derivability adjudication was triggered).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Notes**
- Suite: 105 tests across `test_suite/test_01…test_32`, run under `--isolation per-test-server` (server restarted before each test), so the in-memory-only storage requirement is exercised 105× per round and holds.
- Implementation is 20 files under `workspace/implementation/` (Flask, in-memory dicts, global RLock); logical clock defaults to `2026-08-01T00:00:00Z` and expiry happens only via `/_compliance/sweep`, matching PRD §2.4.
- Cleaned up the sweep artifacts afterwards (`results.*.json`, `sweep.log`, `__pycache__`) so the implementation directory ships clean.

Note (orchestrator): the Step 7 subagent deleted its own `results.*.json` evidence on exit, but the pipeline output contract lists `results.{1..8}.json` as a required artifact. The orchestrator therefore re-ran one full 8-round `setsid`-wrapped sweep itself to regenerate the evidence and to independently verify the 105/105 claim rather than take it on trust. Result of that verification sweep is recorded in the Step 7-verify entry below.

## Step 7-verify: Orchestrator re-run of the 8-round sweep — 2026-09-02T13:15:00.000Z

Independent re-run by the orchestrator (not the Step 7 subagent), wrapped in `setsid nohup` so no foreground Bash return could reap the backgrounded rounds. Launched 2026-09-02T13:10:35Z, all 8 rounds joined by 13:14:38Z (~243s wall for the concurrent set).

Command shape: `prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" --test-dir .../test_suite --isolation per-test-server --timeout 120 --test-timeout 30 --results-file .../results.$i.json` × 8 concurrent, no `--api-url` (runner claimed its own port per round; ports 49811 etc. via the flock'd port registry).

Result — read back from the regenerated `results.{1..8}.json`:

| round | passed | total | failed | errors |
|-------|--------|-------|--------|--------|
| 1 | 105 | 105 | 0 | 0 |
| 2 | 105 | 105 | 0 | 0 |
| 3 | 105 | 105 | 0 | 0 |
| 4 | 105 | 105 | 0 | 0 |
| 5 | 105 | 105 | 0 | 0 |
| 6 | 105 | 105 | 0 | 0 |
| 7 | 105 | 105 | 0 | 0 |
| 8 | 105 | 105 | 0 | 0 |

`grep -c "FAILED\|ERROR" sweep.log` == 0. No `Terminated` in any server log, so no reaping occurred. Step 7's 105/105 claim is confirmed on fresh evidence, and the required `results.{1..8}.json` artifacts are now present in `workspace/implementation/` as the output contract requires. No implementation or test changes were made during verification.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:15:30.000Z

Skip condition met per the skill: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With no Step 7 diff there is no `<step_7_diff>` focus list to patch against, and PRD.md already determined every behavior the tests exercised. No subagent spawned; `PRD_FINALIZED.md` is intentionally absent. Step 9 therefore takes `workspace/PRD.md` as its source.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:20:00.000Z

Done. `PRD_COMPLETED.md` written; `implementation/` untouched.

## Source vs output
- Source: `PRD.md` (no `PRD_FINALIZED.md` present) — 429 lines, 87,234 chars
- `PRD_COMPLETED.md` — 429 lines, 94,266 chars (**+7,032 chars**, all in-paragraph inserts/revisions; no new sections, no new paragraphs)

## Counts
- **Ambiguity pins (PRD silent): 30**
- **Mismatch revisions (PRD said otherwise): 12**

## Changes
- §2.1 — revise — ambiguity — a context header present but empty counts as missing for `ERR_UNAUTHENTICATED` — `auth.py:30`
- §2.1 — insert — ambiguity — acting `X-User-ID` is never resolved against the roster; only body-named witness/advocate ids are — `auth.py:26-34`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 random uppercase-alphanumeric chars — `envelope.py:15`
- §2.2 — revise — mismatch — `api_request_timestamp` is read from the real wall clock, not the §2.4 logical clock — `envelope.py:21`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is a schema failure; `offset` has no upper bound — `validation.py:107-123`
- §2.3 — revise — ambiguity — `created_at` ties break by creation sequence, earliest-written first — `store.py:73-78`
- §2.3 — insert — ambiguity — filters compare stringified field values; empty-string filters and undocumented params are ignored — `validation.py:127-141`
- §2.4 — revise — ambiguity — missing/unparseable `to_iso8601` is `ERR_INVALID_REQUEST`; backwards moves allowed; `data` carries only `current_utc` — `routes/ops.py:23-30`
- §2.4 — revise — ambiguity — the four sweep families run in the listed order, each walking rows by ascending `created_at`, later families seeing earlier effects; `data` carries only the four counts — `routes/ops.py:124-136`
- §2.4 — revise — ambiguity — discharge-request expiry needs the clock *strictly* past the deadline — `routes/ops.py:91`
- §2.5 — insert — mismatch — on placement the body's `unit_id` resolves before the path's admission (band order overrides path-before-body) — `routes/admissions.py:217-220`
- §2.6 — revise — ambiguity — client instants accepted with any offset, normalized to UTC, truncated to ms — `timeutil.py:45-60`
- §2.9 rule 3 — insert — ambiguity — empty/whitespace strings, uniqueness collisions (`license_number`, `mrn`, in-room `bed_label`), missing `capacity_determination_id`/`emergency_justification` all land in the schema band — `validation.py:43`, `roster.py:39,127,188`, `consents.py:133-136`
- §3.1 — insert — ambiguity — unknown clinician read → `ERR_REFERENCED_RESOURCE_NOT_FOUND` — `roster.py:55-61`
- §3.1 — revise — ambiguity — bed PATCH accepts all four statuses incl. `OCCUPIED`, no admission cross-check, and a no-op restatement still bumps `Bed.version` and re-runs the unit recomputation — `roster.py:160-174`
- §3.2 — insert — ambiguity — any authorized role may sign; no check against `evaluating_clinician_id` — `routes/evaluations.py:61-75`
- §3.3 — revise — mismatch — `certification_note` is optional and persisted nowhere — `routes/holds.py:94`
- §3.3 — revise — mismatch — an admission already `INVOLUNTARY` is untouched; its `version` does not move on certification — `routes/holds.py:113-116`
- §3.3 — insert — mismatch — conversion closes the earliest-created `ACTIVE` hold and runs no further links (other admissions untouched, no discharge request granted) — `routes/admissions.py:281-288`
- §3.3 — revise — mismatch — expiry's admission links fire only when the recomputed `active_hold_count` hits 0, and expiry answers no discharge request / advances no placement axis — `cascades.py:136-159`
- §3.4 — revise — mismatch — `withdraw_reason` is neither required nor persisted — `routes/holds.py:219`
- §3.4 — insert — ambiguity — outcome recording tests petition status, then hearing status, then `ERR_HOLD_NOT_ACTIVE`, then the continuance limit — `routes/holds.py:384-395`
- §3.4 — insert — ambiguity — successor hold keeps `initiated_by_clinician_id`, `certified_at`, `closure_reason` null — `routes/holds.py:341-347`
- §3.4 — insert — ambiguity — a continued hearing keeps `outcome` `PENDING`, stores `findings_note`, and the petition's status+counter change is a single version bump — `routes/holds.py:366-371`
- §3.4 — revise — ambiguity — court-denial-granted discharge requests get `decision` `GRANT` with a null `responding_clinician_id` — `cascades.py:114-115`, `routes/holds.py:363`
- §3.5 — insert — mismatch — admission FKs resolve patient → unit → evaluation (band order, not prose order) — `routes/admissions.py:77-85`
- §3.5 — revise — ambiguity — creation also sets `search_items_secured_count` 0, `contraband_found` false, `search_witness_clinician_id`/`search_type` null — `routes/admissions.py:101-121`
- §3.5 — revise — ambiguity — the body's `unit_id`, not the admission's, governs version/posture/beds, and the two need not agree — `routes/admissions.py:212-253`
- §3.5 — insert — ambiguity — named-bed cohort test runs first and only for beds on the requested unit; auto-selection reports no cohort error at all — `routes/admissions.py:234-242`
- §3.6 — insert — ambiguity — restraint ordering has no placement/legal-axis gate — `routes/restraints.py:46-48`
- §3.6 — insert — ambiguity — episode creation nulls all release/compliance/debrief fields and starts an empty log — `routes/restraints.py:78-89`
- §3.6 — revise — mismatch — `assessment_note` optional and not persisted — `routes/restraints.py:98-101`
- §3.6 — revise — mismatch — `release_note` optional and not persisted — `routes/restraints.py:143-146`
- §3.6 — revise — ambiguity — `actual_duration_minutes` floors at 0 — `routes/restraints.py:152-156`
- §3.6 — revise — mismatch — `debrief_note` required but not persisted — `routes/restraints.py:173`
- §3.6 — revise — mismatch — a zero-`required_check_count` episode debriefs on an empty log (grid is 100.0 by definition) — `calc.py:122-125`, `routes/restraints.py:178`
- §3.6 — insert — ambiguity — both sweep branches recompute the owning unit once via the rights-violation link, regardless of intervention type — `routes/ops.py:76-80`
- §3.7 — insert — ambiguity — omitted `capacity_determination_id` on a surrogate basis is `ERR_INVALID_REQUEST` — `routes/consents.py:133`
- §3.7 — revise — ambiguity — missing/empty `emergency_justification` is `ERR_INVALID_REQUEST`; a non-`INVOLUNTARY` admission also yields `ERR_NO_ACTIVE_HOLD` — `routes/consents.py:135,163-166`
- §3.7 — insert — ambiguity — a `capacity_determination_id` cited on a non-surrogate basis is still resolved (404 if unknown) then stored as null — `routes/consents.py:141-145,173`
- §3.8 — revise — ambiguity — sweep expiry needs the clock strictly past the deadline and leaves `decision` `PENDING` / `responding_clinician_id` null — `routes/ops.py:90-99`
- §3.8 — insert — ambiguity — a second discharge-plan submission is accepted and overwrites the stored plan — `routes/admissions.py:303-318`

Cross-checks that needed no change: all 51 endpoint role lists and status codes, the §5 error/HTTP table, §2.9's numbered band order against every route's actual check sequence, the four-step posture computation, both hold-deadline variants, the business-hours response deadline, both compliance measures, per-episode staffing ceilings, the bed selector's five ranking keys and the promotion queue's three.

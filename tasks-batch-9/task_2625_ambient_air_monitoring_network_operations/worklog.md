# Worklog — task_2625_ambient_air_monitoring_network_operations

## Step 1: Create Task Directory — 2026-09-03T21:18:42.868Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations` and its `workspace/` subdirectory. Index 2625 was pre-assigned by the invoking command; no scan of `./tasks/` was performed and no index was auto-allocated (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate Scaffold — 2026-09-03T22:41:30.000Z

All three scaffold artifacts are complete and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD.yaml` — 2820 lines, 153 KB
- `/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1769 lines, 119 KB (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD_CORNER_DESIGN.yaml` — 5588 lines, 368 KB (single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts (§1.0–§1.7)
entities 14 · state_machines 12 blocks over 11 entities (DataBatch carries two independent dimensions) · concurrency_rules 2 · calculations 8 · validations 38 · endpoints 65 · errors 44 · roles 5. Profile: `compliance_audit` / `temporal_windowing`, layers optimistic_concurrency + cascading_side_effects + dual_variant_calculation + rate_threshold_triggers, topology graph, shape cyclic, role_model segregation_of_duties, consistency immediate, difficulty beyond_expert. Only test-driving endpoint: `POST /_clock/set_current_utc`.

## §1.8 — 9 rule ids × 2 instances = 18
`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2.

## §1.9 — 104 instances across the 9 taxonomy sections (79 with recipes, 25 `excluded_because` stubs)
entities 12 (0 stubs) · state_machines 20 (4) · calculations 13 (4) · validations 24 (5) · endpoints 9 (1) · errors 11 (8) · rbac 7 (0) · cross_cutting_complexity_layers 7 (3) · consistency_model 1 (0). Every stub cites an existing §1.8 instance by name and carries no `test_recipe`.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  1333

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Beyond the lint I ran my own audit script over both design files: 0 duplicate names across 122 instances, 0 unbound `${var}` in any payload/path/assert, 0 stubs with a recipe, 0 unresolvable `grounds` after normalization.

## Design adjudications made in this session
- **Enum leak fixed**: a §1.8 assert claimed `batch_invalidation_reason == SITE_TERMINATED`, which is not in the declared enum `{QA_REJECTED, MONITOR_DECOMMISSIONED}` → corrected to `MONITOR_DECOMMISSIONED`.
- **Contradiction between §1.2 and §1.5 resolved**: the shutdown cascade's hop 4 said the demoted package keeps `rejection_count` unchanged while the decision endpoint said it increments (and the §1.8 instance asserts 1) → §1.2 now says "incremented by 1".
- **§1.3/§1.5 gap closed**: `POST /data-batches/{id}/invalidations` now declares the `certification_package_rollup` refresh that §1.3's trigger clause already implied; this is what the `consistency_model` instance asserts.
- **complexity_profile comment corrected**: it claimed "five of the ten machines" are cyclic; the scaffold has 12 machine blocks and 8 cyclic ones, now enumerated explicitly.
- **Grounds citation style normalized** (`validations[priority=N]`, `concurrency_rules.<rule_id>`) and one wrong calculation name (`qc_event_outcome` → `qc_event_outcome_evaluation`) fixed.
- **Arithmetic recomputed, not estimated**: rollup from summed hours `100*3252/4344 → 74.9` (vs the forbidden average-of-percentages 75.0); `100*7680/8760 → 87.7` (initially written 87.6, corrected); `100*2060/2160 → 95.4`; `100*1960/2160 → 90.7`; adequacy `100*1.0*0.9*1.0 = 90.0` at the inclusive ADEQUATE bound; annual means 9.25→9.3, 9.05→9.1, 8.95→9.0.
- **Reachability adjudications**: the `defaults` corner instance forced three POST endpoints (`/pollutants`, `/monitoring-sites`, `/monitors`) to mark defaulted fields optional; the `not_found` and `parent_relationships` instances pinned left-to-right FK validation order; the OCC corners take `version` from a GET capture rather than a literal so cascade bumps cannot stale them.

Orchestrator verification: all three files exist, parse as valid YAML, and carry the expected top-level keys (`SCAFFOLD.yaml` has no `scaffold_difficulty_design`/`scaffold_corner_design` key; the two design files each have exactly their single top-level key).

## Step 3: Copy Shared Files — 2026-09-03T22:42:31.598Z

Copied `./INSTRUCTION.md` → `tasks/task_2625_ambient_air_monitoring_network_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T22:54:40.000Z

PRD.md is complete end-to-end at `/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/workspace/PRD.md`.

**Line count:** 461 lines / ~14,750 words. Written in 8 chunked appends; document ends at the final row of the §5 error table with no audit footer.

**Section headings**
- `# Ambient Air Monitoring Network Operations API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Revision Counter · 2.5 The Logical Clock · 2.6 Resolving Path Segments and Body References · 2.7 Optimistic Concurrency on Quarters and Sites · 2.8 Precision, Rounding and Truncation · 2.9 Cascade Discipline and the Network Census · 2.10 Segregation of Duties · 2.11 Rejection Precedence
- `## 3. Business Logic & Workflows` — 3.1 The Pollutant Catalogue and Federal Method Designation · 3.2 Network Registration, Site Siting and Regional Approval · 3.3 Instrument Lifecycle, Quality-Control Activity and QC Posture · 3.4 Reporting Monitor-Quarters and the Hour Budget · 3.5 The Validation Dimension: Review, Rejection and Reopening · 3.6 Exceptional-Event Demonstrations and Hour Exclusion · 3.7 Design Values and Attainment Determination · 3.8 Annual Certification and the Submission Dimension · 3.9 Network Assessment, Relocation, Suspension and Shutdown
- `## 4. Endpoint Definitions` (4 columns) · `## 5. Error Code Catalogue` (2 columns)

**Coverage (documented / declared)**
| Category | Declared | Documented |
|---|---|---|
| Endpoints | 65 | 65 (all method+path rows verified against scaffold) |
| Errors | 44 | 44 in §5 table, 44/44 also triggered in §2/§3 prose; 0 invented |
| Entities | 14 | 14; 144/144 `fields[].name` present in backticks |
| Endpoint identifiers | 86 body + 31 query/path | 86/86 and 31/31 present |
| Validations | 38 | 38, each paired with its `error_id`; all multi-endpoint `applies_to` sets enumerated |
| Calculations | 8 | 8 (incl. all 3 dual-variant pairs), formulas in prose with constants embedded |
| State machines / transitions | 12 / 53 | all `from`/`to` pairs, preconditions and side-effect cascades expressed |
| OCC rules | 2 | 2 (`expected_data_batch_version`/`ERR_STALE_BATCH_VERSION` 412, `expected_monitoring_site_version`/`ERR_STALE_SITE_VERSION` 412) |
| Roles | 5 | 5, all `identity: opaque` translated |

**Hard contracts**
```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params/path_params: 31 required, 31 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ_field + error_id + status), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 65 checked, 65 expressed, 0 missing
- entities[].fields[] structured content: 144 checked, 144 reconstructible (defaults, enums, ranges, null-semantics), 0 missing
- sibling-branch symmetry: 9 groups checked (CONCUR/NON_CONCUR, APPROVE/DENY/REQUEST_REVISION, APPROVE/RETURN, 3 request_type cascades, DESIGNATED<->CONDITIONAL->WITHDRAWN, service-status both directions, 2 design-value variants, 2 posture variants, 3 standard_form branches), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 975 (333 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 12 state machines' state strings and every `enum` member appear verbatim; no fuzzy/approximating words ("approximately", "roughly", "conservatively", "~", etc.) anywhere.

Three fidelity repairs were made during the Contract 2 walk, worth flagging: (1) §3.7 originally put the `ERR_DESIGN_VALUE_FINALIZED` check before primary-monitor selection, contradicting the scaffold's priority 51 < 64 ordering — reordered; (2) the two OCC write endpoints are now named explicitly by path in §2.7 (legal there, §3 stays pure); (3) the bulk-ingest paragraph now states the quarter-has-ended test explicitly rather than only by reference. Two internal scaffold inconsistencies were resolved in favour of the authoritative enum: `stale_reason` on the reopen path is documented as `BATCH_REVALIDATED` (the endpoint's `side_effects` said `BATCH_REOPENED`, which is not a member of the field's enum), and the demonstration `event_type` list follows the enum (`WILDFIRE`/`HIGH_WIND_DUST`/`PRESCRIBED_FIRE`/`STRATOSPHERIC_INTRUSION`) rather than the endpoint description's stray "volcanic-activity". Neither design file was opened.

**Orchestrator anti-truncation verification**: `wc -l` = 461 lines / 108,159 bytes. `tail -25` ends at the final `| ERR_NO_ELIGIBLE_BATCHES | 422 |` row of the §5 error table — a real section boundary, not mid-sentence. §4 contains exactly 65 endpoint rows and §5 exactly 44 error rows, matching the scaffold's declared counts. Grep for `harder than expert` / `beyond_expert` / `difficulty` in PRD.md returns 0 hits, so the Step 2-only difficulty instruction did not leak into the contract. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T23:25:30.000Z

The implementation is complete.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/workspace/implementation/`

## Modules (3,712 lines total, all `py_compile` clean)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | launcher; guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 67 | blueprint registration, `ApiError`/404/405/HTTPException/500 envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 60 | in-memory dicts (14 collections), id/`_seq`/common-field helpers |
| `clock.py` | 27 | logical clock, default exactly `2026-08-01T00:00:00Z`, 3-fractional-digit ISO |
| `errors.py` | 60 | all 44 error ids -> HTTP status |
| `response.py` | 55 | `meta`/`response_type`/`data` envelope, `req_`-prefixed request id, pagination meta |
| `auth.py` | 61 | `X-User-ID` + `X-User-Role`, 5 roles, `require()` |
| `validate.py` | 259 | structural typing/range checks, pagination (10/1/100, offset >= 0) |
| `constants.py` | 110 | every enum set + all calculation constants |
| `services/compute.py` | 544 | all 8 calculations, graph walks, quarter arithmetic, network census |
| `services/serialize.py` | 334 | per-entity serializers with computed-field refresh on read |
| `services/cascade.py` | 270 | 5-hop shutdown/relocation, 5-hop concurrence, 3-hop suspension/reinstatement, package rollup re-runs, DV supersession |
| `routes/common.py` | 103 | 404 lookups, terminal/from-state guards |
| `routes/{pollutants,networks,sites,monitors,batches,demos,design_values,packages,assessments,change_requests,clock_routes}.py` | 1,603 | the 65 endpoints |

## Endpoint coverage: 65 / 65

I extracted every `method`+`path` pair from `SCAFFOLD.yaml`'s `endpoints:` block and diffed it against Flask's live `url_map` (path params normalized): **the two sets are byte-identical, 65 vs 65, zero extra and zero missing routes.**

## Smoke test: passed

Launched with `PORT=18625 bash start.sh`, then killed by port-resolved PID (`ss -ltnp` -> `kill <pid>`) — no pattern kill was ever used. Beyond the mandated couple of curls I ran a full workflow through the running server:

- envelope/auth: unauthenticated 401 `ERR_UNAUTHENTICATED`; wrong role 403 `ERR_UNAUTHORIZED`; unknown route 404; `limit=500` -> 400 `ERR_INVALID_REQUEST`; unknown id -> 404 `ERR_PACKAGE_NOT_FOUND`
- catalogue -> network -> site (siting eval ran on create, `siting_violation_codes: []`) -> siting approval -> commence operations -> monitor install (duplicate POC -> 409 `ERR_DUPLICATE_MONITOR_POC`) -> approve -> commission -> passing span check moved posture `QC_DELINQUENT` -> `QC_CURRENT`
- 4 quarters ingested and validated; hour accounting correct (2160/2160, 100.0, eligible)
- package opened with `certification_deadline` pinned to `2027-05-01T00:00:00.000Z` and rollup 4/4/100.0/ready -> submit promoted batches to `SUBMITTED` -> certify as the validating officer returned 403 `ERR_SEGREGATION_OF_DUTIES`, certify as a different id promoted them to `CERTIFIED` -> reopening a certified quarter returned 409 `ERR_BATCH_CERTIFIED`
- design value: wrong `expected_monitoring_site_version` -> 412 `ERR_STALE_SITE_VERSION`; correct -> 201 with `complete_year_count: 1`, `attainment_status: INSUFFICIENT_DATA`; finalize -> 422 `ERR_DESIGN_VALUE_INCOMPLETE`
- assessment scored 1 / 0.3333 / 33.3 / `INADEQUATE`, submit set the network `UNDER_ASSESSMENT`, approve returned it to `ACTIVE`
- change request: relocation without replacement -> 422 `ERR_REPLACEMENT_SITE_REQUIRED`; seasonal suspension approved and the 3-hop cascade fired (site `SUSPENDED` + `suspended_at`, monitor `OUT_OF_SERVICE`, `operating_monitor_count` 0); reinstatement restored exactly that monitor and cleared `out_of_service_since`
- demonstration + exclusion + concurrence: the 5-hop cascade moved the exclusion `PROPOSED -> EFFECTIVE` with `effective_at` stamped and recomputed `excluded_hour_total` to 47

Constraints held: storage is dicts only (grep for `sqlite`/`open(`/`json.dump`/`/tmp`/`pickle`/`shelve` across all `.py` returns nothing), no seeding anywhere, and a fresh boot mid-test served an empty store. I never read `test_helpers/`, `test_suite/`, or either `SCAFFOLD_*_DESIGN.yaml`.

One note worth relaying: I resolved several PRD-vs-scaffold conflicts in favour of the PRD, the notable ones being `stale_reason: BATCH_REVALIDATED` on reopen (not the scaffold table's `BATCH_REOPENED`), terminal-state checks placed before from-state checks so `ERR_ALREADY_TERMINAL` stays reachable, and the five undeclared uniqueness constraints (pollutant `code`, network `agency_code`, method `method_code`, package key, assessment key) returning `ERR_INVALID_REQUEST` 400 since the catalogue has no dedicated code for them.

## Step 5: Generate Unit Tests — 2026-09-03T23:41:20.000Z

Generation and audit are complete. All 97 non-stub design instances are translated; nothing was skipped.

## Files

**`test_helpers/` (task root, 1720 lines)** — `__init__.py` 116, `api_client.py` 340 (65 endpoint methods), `api_errors.py` 118 (44 `ERR_*` + `ERROR_HTTP_STATUS` registered via `set_error_http_status_map`), `assertions.py` 135, `constants.py` 152, `factories.py` 238, `fixtures.py` 338, `test_users.py` 54, `types.py` 229.

**`test_suite/` (task root, 5870 lines, 115 tests)**

| File | Lines | Tests | Queue |
|---|---|---|---|
| conftest.py | 80 | – | – |
| test_01_design_value_variants.py | 142 | 4 | A |
| test_02_formula_combinatorics.py | 164 | 4 | A |
| test_03_state_machine_dimensions.py | 133 | 4 | A |
| test_04_transitive_cascades.py | 157 | 4 | A |
| test_05_priority_conflicts.py | 146 | 4 | A |
| test_06_boundary_precision.py | 128 | 4 | A |
| test_07_cross_entity_state.py | 152 | 4 | A |
| test_08_temporal_overlap.py | 181 | 4 | A |
| test_09_compensating_invariants.py | 165 | 4 | A |
| test_10_entities.py | 692 | 12 | B |
| test_11_state_machines.py | 878 | 16 | B |
| test_12_calculations.py | 646 | 9 | B |
| test_13_validations.py | 871 | 19 | B |
| test_14_endpoints.py | 418 | 8 | B |
| test_15_errors.py | 193 | 3 | B |
| test_16_rbac.py | 392 | 7 | B |
| test_17_cross_cutting.py | 267 | 4 | B |
| test_18_consistency.py | 65 | 1 | B |

**Queue A: 36 tests** (18 difficulty instances x 2). **Queue B: 79 tests** (79 non-stub corner instances x 1).

## Audit results

- `ast.parse` clean on all 27 generated `.py` files; `pytest --collect-only` collects **115 tests, 0 errors**; `pyflakes` clean on all of `test_suite/`.
- Every test has **exactly one** `Design:` line and it is the **last** docstring line. All 115 tags resolve: 18/18 difficulty instances covered with >=2 tests each, 79/79 non-stub corner instances covered with exactly 1 each, **0 tags pointing at `excluded_because:` stubs**, 0 tags with a wrong section, 0 untagged/dual-tagged tests.
- All **~270 `PRD x.y: "…"` citations verified byte-verbatim** against `workspace/PRD.md` (0 misses).
- No `skip`/`xfail`/mocking/`monkeypatch`/TODO/placeholder anywhere. No occurrence of "scaffold" in any generated file. Nothing written under `workspace/`.

## Skipped instances

**None.** Every non-stub instance was PRD-derivable. Where a design instance's own expectation contradicted the PRD, the PRD form was emitted (not weakened, not skipped):

- `ERR_INVALID_REQUEST` asserted at **400** (PRD §5), not the yaml's 422.
- `out_of_service_since` stamped from the **logical clock** (PRD §3.3), not the QC event's `performed_at`.
- `waiver_required_site_count` asserted **0** for all-`PROPOSED` networks (PRD §2.9 counts only `SITING_APPROVED`/`OPERATING`/`SUSPENDED`), not the yaml's 3 and 1.
- Event-window projection close bound = hours-to-`event_end_date` **+ 24** = 120 (PRD §3.6), so exclusion legs are `[100,120)`/20 h and `[0,120)`/120 h, not the yaml's `[…,144)`.
- Wholesale batch rejection and the invalidator-SoD test insert a `begin-validation` first, because PRD §3.5 orders the from-state gate ahead of both.
- `event_type: "DUST"` -> **`HIGH_WIND_DUST`** (the yaml value is not in the PRD enum).
- `stale_reason` -> **`BATCH_REVALIDATED`** (PRD §3.5; SCAFFOLD.yaml's side-effect prose says `BATCH_REOPENED`).
- Consecutive-QC-failure test uses drifts 8.0/9.0 (the yaml's 7.0 is a WARN under a 5.0 tolerance).

## Input defect worth flagging

Corner stub `an_incomplete_package_returns_package_not_ready` (`SCAFFOLD_CORNER_DESIGN.yaml` ~line 4614) cites `cross_entity_state_dependency / certification_package_zero_member_batches_blocks_submit`. The instance name resolves (difficulty yaml line 1087) but it lives under `rule_id: boundary_precision_check`, not `cross_entity_state_dependency` — the target exists, the cited rule id is wrong. Harmless here (stubs emit nothing), but the cross-reference is broken in the source index.

Orchestrator verification: `test_helpers/` and `test_suite/` both landed at the task root; no stray copies exist under `workspace/`. Steps 5 and 6 were launched in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it.

## Step 7: Run Tests and Iterate — 2026-09-03T23:57:10.000Z

Verified clean. Exiting with the summary.

## Summary

**Iterations run: 2** (two full 8-round parallel sweeps).

- **Sweep 1:** 111/115 in all 8 rounds — 4 failures, perfectly deterministic (identical set every round, no flakiness).
- **Sweep 2:** 115/115 in all 8 rounds, 0 failed / 0 errors / 0 skipped, 115 tests collected per round. All 8 `results.$i.json` present and verified complete.

**Tests deleted: none.** All 4 failures traced to a single test-side field-name slip that STEP 1 cleared on both sub-checks (PRD verbatim-covers the site lifecycle transitions, and uniquely determines them), so deletion was not warranted.

**Fixes applied to `test_helpers/`: none.** The shared-symptom triage hint pointed at test_helpers first, but the offending symbol lived in the test functions themselves; `test_helpers/fixtures.py::read_site()` correctly returns the site resource dict unwrapped.

**Fixes applied to `test_suite/` (4 assertions, 2 files):**
- `test_suite/test_07_cross_entity_state.py` lines 117, 151 — `env.read_site()["site_status"]` -> `["status"]`.
- `test_suite/test_09_compensating_invariants.py` lines 115, 147 — `site["site_status"]` -> `site["status"]`.

**Fixes applied to `implementation/`: none.** The implementation was correct as written.

### Root cause

All four tests raised a bare `KeyError: 'site_status'` — a wrong key on the response dict, not a failed assertion, which is why the error detail carried no expected-vs-actual values. The site resource has no `site_status` field, and the token appears nowhere in PRD.md. The PRD consistently names the site's lifecycle field plain `status`:

- §3.2: "A proposed site enters `status` `PROPOSED` with `siting_waiver_granted` false"
- §3.2: sites are "listed with filters on `network_id`, … on `site_type`, on `status`"
- §3.9: "the nominated replacement site must have `status` `SITING_APPROVED` or `OPERATING`"

The prefixed spelling is real elsewhere in the schema — `network_status` on a network, `monitor_status` on an instrument, `validation_status`/`submission_status` on a quarter — and the test author over-generalized that convention onto the site. `workspace/implementation/services/serialize.py::site()` (line 103) emits `"status"`, matching the PRD. So the implementation was PRD-faithful and the assertion was not; per STEP 2 the fix belonged in the test.

This was a pure key rename that preserved every asserted state value exactly (`SUSPENDED`, `OPERATING`, `SHUTDOWN`) — no assertion was weakened, and no skip/xfail was introduced. Notably, the `KeyError` fired on the *first* assertion in both `test_09` tests, masking everything downstream (the `suspended_at` timestamp, monitor posture recomputation, `out_of_service_day_count == 10`, and the census-partition invariant). Those previously-unreached assertions all passed once the key was corrected, confirming the suspension/reinstatement cascade and out-of-service accrual were already implemented correctly.

**Orchestrator independent verification** (not taking the subagent's word — a Step 7 agent can claim a clean sweep with no artifacts behind it): all 8 `workspace/implementation/results.{1..8}.json` exist, timestamped Sep 3 23:56, and each parses to `total 115 / passed 115 / failed 0 / errors 0 / skipped 0`. Grep for `pytest.mark.skip` / `xfail` across `test_suite/` and `test_helpers/` returns 0 hits, confirming no test was dodged rather than fixed.

**Step 8 skip decision**: NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 ran 2 iterations and applied 4 `test_suite/` fixes, so Step 8 runs with the above entry inlined as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-04T00:05:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2625_ambient_air_monitoring_network_operations/workspace/PRD_FINALIZED.md` is produced and is **byte-identical to PRD.md** (461 lines each, md5 `ed01eb31ca6bf44f04fc4d455ada3442`, 0 lines changed, 0.0% delta). The correct minimal patch is **zero edits**.

## Why zero edits

`<step_7_diff>` contains exactly one class of item: 4 test-side assertion fixes renaming `site_status` -> `status` in `test_suite/test_07_cross_entity_state.py` (lines 117, 151) and `test_suite/test_09_compensating_invariants.py` (lines 115, 147). No implementation fixes, no test deletions, no `test_helpers/` fixes. I verified this was a pure fixture/test bug with no PRD silence and no PRD/impl divergence:

- `grep -rn "site_status"` across the whole workspace (`*.py`, `*.md`) returns **zero hits** — the token exists neither in PRD.md nor anywhere in `implementation/`. It was never a competing spelling, just a wrong key.
- `implementation/services/serialize.py::site()` line 103 emits `"status": rec["status"]`; the site resource has no prefixed variant.
- The site status field name is verbatim-pinned by PRD.md in multiple places: line 170 ("A proposed site enters `status` `PROPOSED`"), line 180 (list filters "on `site_type`, on `status`"), line 330 (replacement site "must have `status` `SITING_APPROVED` or `OPERATING`"). §2.9 line 124 enumerates the six lifecycle values (`PROPOSED`, `SITING_APPROVED`, `OPERATING`, `SUSPENDED`, `SHUTDOWN`, `RELOCATED`) that the corrected assertions read.
- Every behavior the previously-masked assertions exercise is already stated verbatim: §3.9 line 332 (suspension stamps `suspended_at`, census bucket shift with `total_site_count` unchanged, monitors `OPERATING -> OUT_OF_SERVICE`), §3.9 line 334 (reinstatement inverse, whole-days accrual into `out_of_service_day_count`, both postures recomputed), §3.9 line 336 (`SHUTDOWN` cascade to `DECOMMISSIONED`). No impl choice is left open by the PRD at any of the four sites.

## Per-edit pre-edit search log

No edits were committed, but the mandatory search was still run for the single candidate subject:

- **(a) Subject identified:** the name and value domain of the monitoring site's lifecycle status field as exposed on the site resource.
- **(b) Impl paths enumerated (read/grepped):** `implementation/services/serialize.py::site()` (emitter, line 103) and its sibling emitters `monitor()`/network/quarter to confirm the prefixed convention (`monitor_status`, `network_status`, `validation_status`, `submission_status`) genuinely stops short of the site; `implementation/routes/sites.py` lines 55, 76-77, 83, 99-101, 117-118, 136, 148 (creation default, siting-approval, commissioning, reinstatement guards, list filter, terminal-state guard); `implementation/routes/monitors.py` lines 78, 100, 136 (site-status preconditions on instrument approval/commissioning/QC paths); `implementation/routes/change_requests.py` lines 22-24 (`ERR_SITE_NOT_OPERATING` gate); `implementation/services/cascade.py` and `compute.py` for the suspension/reinstatement/shutdown hops and census recomputation. All read `site["status"]` — no path anywhere in the impl, on or off the Step 7 site, uses a prefixed spelling.
- **(c) Wording adjustment:** none needed — PRD prose already matches every enumerated path, so per the method ("Where PRD already determines behavior, keep prose verbatim") no edit was made. Adding any clarifying sentence here would have risked a new-mismatch for no gain.

Orchestrator note: byte-identity between `PRD.md` and `PRD_FINALIZED.md` is the expected outcome here rather than a sign the pass was skipped — Step 7 applied 0 `implementation/` fixes and made 0 deletions, so there was no PRD-silence or PRD-mismatch site for Step 8 to patch. Step 9 (which always runs, and does the full impl-vs-PRD scan) starts from `PRD_FINALIZED.md`. Because a Step 9 scan of a 3,700-line implementation against a 461-line PRD is too large to be trustworthy in one agent, it is being run as three sequential file-partitioned passes, each editing `PRD_COMPLETED.md` in place.

## Step 9: Complete PRD — 2026-09-04T00:31:00.000Z

Run as three sequential file-partitioned passes over `implementation/`, each editing `workspace/PRD_COMPLETED.md` in place (seeded by the orchestrator as a copy of `PRD_FINALIZED.md`). Partitioning was chosen because a single agent scanning 3,703 lines of implementation against a 461-line PRD cannot be exhaustive; a byte-identical PRD_COMPLETED.md is the known failure signature of an unpartitioned scan.

**Cumulative: 57 edits (46 ambiguity-pins, 13 mismatch-revisions), all in-paragraph. 461 lines -> 461 lines, 108,159 -> 119,334 chars (+11,175).**

### Pass 1 — app/auth/clock/db/errors/response/validate + routes/{common,pollutants,networks,sites,monitors,clock_routes}.py
24 edits (22 ambiguity-pins, 2 mismatch-revisions), +4,961 chars.
- §2.1 insert: empty header counts as absent for `ERR_UNAUTHENTICATED` — auth.py:37
- §2.2 insert: `api_request_id` = `req_` + 20 upper-case-alphanumerics — response.py:13
- §2.2 insert: `api_request_timestamp` read from the logical clock, never host time — response.py:19
- §2.3 insert: ties break by persistence order; identifiers never order rows; enum/int/bool filter values validated while an unmatched identifier filter yields an empty page — db.py:60, monitors.py:255, validate.py:225-259
- §2.4 revise (mismatch): the "second resource's `version` increments" universal now excludes purely derived counters — sites.py:65, monitors.py:87
- §2.5 insert: `to_iso8601` may move the clock backwards; clock-set eagerly refreshes both postures on every non-decommissioned instrument and bumps no `version`/`updated_at` — clock_routes.py:19,22-23
- §2.11 revise (mismatch): state-check order is terminal -> own from-state -> cross-row, not from-state first — common.py:71-85 (uniform across 20 call sites)
- §3.1 inserts: duplicate pollutant `code` and duplicate `method_code` -> `ERR_INVALID_REQUEST` 400 (checked before `pollutant_id` resolves); `design_value_years` >= 1 with no upper bound — pollutants.py:24,28-30,78-81
- §3.2 inserts: duplicate `agency_code` -> 400; `agency_code` non-empty; `metropolitan_population`/`population_served` integer; proposing a site refreshes the census without bumping the network `version`; `GET /monitoring-sites` re-evaluates siting before the `siting_waiver_required` filter — networks.py:22-25, sites.py:29,65,139-150
- §3.3 inserts: the `delinquent_monitor_count` recompute never bumps the network `version`; the `OUT_OF_SERVICE` direction bumps only the instrument's; `DECOMMISSIONED` yields `ERR_ALREADY_TERMINAL` ahead of the from-state check; `performed_at` after the clock -> 400 before the path monitor resolves; off-type drift fields persist null and `declared_failure` is echoed for every type; the FAIL auto-out-of-service does not bump the site `version`; `GET /monitors` recomputes both postures before the `qc_posture` filter — monitors.py:75,86-87,97,108-110,121,129-130,147-149,166-179,198-199,203-205,225-226
- §4 insert: unknown path/method -> envelope with `ERR_INVALID_REQUEST` under HTTP 404/405; every `*_note`/`certification_statement`/`reopen_reason`/`rejection_reason`/`info_request_note` is validated but never persisted or returned — app.py:42-58
- Already fully pinned, no edits: `errors.py` (all 44 ids/statuses match §5), `clock.py`, networks list endpoints, the pollutant designation machine, siting-approval/commence-operations version+census effects, the install uniqueness triple, `response.py` pagination `has_more`, `auth.py` role set.

### Pass 2 — routes/{batches,demos,design_values}.py + services/compute.py
19 edits (14 ambiguity-pins, 5 mismatch-revisions), +3,635 chars.
- §2.3 revise (mismatch): "identifiers never participate in ordering" was false — the exclusion listing orders by the `data_batch_id` FK; narrowed to a row's own `id` — demos.py:212
- §2.4 revise: carve-out extended to a site's `current_attainment_status` and a package's four rollup figures — batches.py:205,306 / cascade.py:36-40
- §2.11 revise (mismatch): added the closed-hour-ledger guard on invalidation withdrawal as the one local exception — batches.py:317-321
- §3.2 revise: `current_attainment_status` tie-break is most-recently-persisted-first when `created_at` and `period_end_year` both tie — compute.py:369
- §3.4: neither optional measurement may be negative; `batches` >= 1 item; **bulk ingest does NOT report the first offending item's error** — rules run in §2.11 precedence rule-by-rule across the whole list, so an earlier not-ended item loses to a later duplicate (HTTP 201 + array in request order); hour accounting also reruns on wholesale rejection, on the §3.9 write-off cascade and on every read; `withdrawn_reason` non-empty; the closed-ledger check precedes the invalidation's own terminal/from-state checks so a second withdrawal on a written-off quarter yields `ERR_INVALID_STATE` not `ERR_ALREADY_TERMINAL`; the quarter listing re-runs accounting before the `regulatory_use_eligible` filter — batches.py:30-32,85-98,181,228,314,316-321,227-240 / serialize.py:163
- §3.5: bulk-validate `year` bounded 2000-2100; `reopen_reason` non-empty — batches.py:127,191
- §3.6: `clear_causal_relationship` required and `event_end_date` < `event_start_date` -> 400 before either reference resolves; two exclusion ranges may freely overlap each other (only invalidation collision is barred); containment is measured against the quarter's **calendar** hour span, not `scheduled_hour_count`; nomination tests nothing else (any demo status, instrument need not sit at the demo's site or measure its pollutant); `info_request_note` non-empty — demos.py:35-38,74-100,87-90,92-100,142 / compute.py:122
- §3.7: dropped the false "creation times compared at millisecond resolution" (a `poc`+`created_at` tie falls to persistence order, earlier row wins); `FOURTH_MAX_8HR` passes over null `fourth_high_daily_max` and an all-null year yields raw annual 0; `EXCLUDING_CONCURRED_EVENTS` falls back to `quarterly_mean_concentration` when the event-adjusted mean is null and is a no-op for `FOURTH_MAX_8HR`; finalize refreshes `current_attainment_status` by the §3.2 selection rule, not "from this row" — compute.py:295,302-309,333-335,362 / design_values.py:92
- Already fully pinned, no edits: every `compute.py` calculation core verified line-by-line (siting evaluation's five criteria and inclusive probe band, QC outcome's 2-dp pre-rounding and inclusive limits with 1.5x WARN band, posture banding with 7-day grace, hour accounting S1-S7 with the inclusive threshold on the rounded figure, network census status sets, the package rollup's summed-hours ratio, adequacy scoring's population tiers and capped multiplicative penalties, the certification deadline, `whole_days_between`); design-value gate order and `RECOMPUTED` supersession; the single-report gate order, half-open non-abutting overlap rule and append-only author list.

### Pass 3 — routes/{packages,assessments,change_requests}.py + services/{serialize,cascade}.py + constants.py
14 edits (8 ambiguity-pins, 6 mismatch-revisions), +2,554 chars.
- §2.4 revise (mismatch): the carve-out read as a closed three-item list; widened to a site's siting evaluation, an instrument's two QC postures, a quarter's hour-accounting figures, a demonstration's `excluded_hour_total` and an assessment's four adequacy figures, and stated the recompute alone bumps neither `version` nor `updated_at` — serialize.py:81,120,163,208,269,313
- §2.9 revise (mismatch): "every affected row … `version` incremented" was a false universal; carved out rows whose only change is a §2.4 derived figure — cascade.py:185,260
- §2.11: no change — packages/assessments/change_requests all follow terminal -> own from-state -> cross-row, so the "one local exception" clause stands
- §3.8: duplicate (network, pollutant, year) package -> `ERR_INVALID_REQUEST` 400 after both FKs resolve, opening with `certified_by_user_id`/`certified_at` null; the rollup re-run list now includes the read-time refresh; rejection demotes on the submission dimension alone, so a quarter reopened since submission is demoted too — packages.py:29-44 / serialize.py:313 / cascade.py:47-55
- §3.9: duplicate (network, cycle_year) assessment -> 400 after `network_id` resolves, opening with `submitted_at`/`approved_at`/`approved_by_user_id` null; a second cycle may be submitted while one is pending and overwrites `current_assessment_year`; either decision leaves `current_assessment_year` in place and a `RETURN` leaves the approval fields null; neither `REQUEST_REVISION` nor `DENY` consults the target site's lifecycle status; reinstatement bumps site + each returned instrument + network `version` by exactly 1; cascade hop 4 keys on package **scope** not selected membership, so a quarter written off out of `RAW`/`IN_VALIDATION`/`REOPENED` need not move the rollup at all while a `SUBMITTED` package still returns to `DRAFT`; "every row touched at every hop has its `version` incremented" narrowed to rows whose stored state actually moved; an assessment's scoring is recomputed on read even after approval so an approved cycle's figures are never frozen; a new change request carries `decided_by_user_id`/`decided_at`/`effective_at` null — assessments.py:25-37,49-61,74-86 / change_requests.py:55-57,88-99 / cascade.py:32-33,119-142,176-190 / serialize.py:269-277
- Already fully pinned, no edits: `constants.py` — every enum member set (including the `QC_TIMESTAMP_FIELD` map with `PRECISION_CHECK -> None`) and every numeric constant (2.0/15.0/10.0/500.0/100.0/2.0, 1.5, 7, 4, May 1, 0.10/0.30, 0.05/0.20, 90.0/75.0, the 24 h buffer) already appears uniquely in PRD prose.

**Orchestrator final verification**: `PRD_COMPLETED.md` is 461 lines / 119,334 chars, md5 `2f8630703fcff857c667597f6824d503`, differing from `PRD_FINALIZED.md` (`ed01eb31…`) by 96 changed lines — so the scan demonstrably ran rather than shipping an untouched copy. All 25 headings survive (§1, §2 with 2.1–2.11, §3 with 3.1–3.9, §4, §5); §4 still carries 65 endpoint rows and §5 still 44 error rows; the tail still ends at `| ERR_NO_ELIGIBLE_BATCHES | 422 |`. Step 9 edited PRD prose only — no file under `implementation/`, `test_suite/` or `test_helpers/` was touched after the clean sweep, so the verified 8/8 x 115/115 result still holds. Pipeline complete.

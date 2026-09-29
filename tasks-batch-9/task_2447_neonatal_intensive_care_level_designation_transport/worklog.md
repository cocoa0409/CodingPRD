# Worklog — task_2447_neonatal_intensive_care_level_designation_transport

## Step 1: Create task directory — 2026-09-02T19:44:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport` and its `workspace/` subdirectory. Index 2447 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was allocated locally.

## Step 2: Scaffold artifacts generated — 2026-09-02T21:20:00.000Z

Wrote `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 25 instances
across 9 rule_ids) and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 9 sections / 81 instances,
53 with test recipes and 28 deduplicated onto §1.8 instances). `scaffold_lint.py` reports
`VERDICT: clean lint` (81 endpoints, 13 entities, 1405 calls scanned). No sibling task
directory was read at any point.

### Step 2 subagent summary (verbatim, orchestrator record)

All three artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport/`.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2447_neonatal_intensive_care_level_designation_transport/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2447_neonatal_intensive_care_level_designation_transport/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2447_neonatal_intensive_care_level_designation_transport/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    81
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1405

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

`SCAFFOLD.yaml` (2322 lines, §1.0–§1.7 only — no difficulty/corner keys): 13 entities, 8 state machines, 3 concurrency rules (unit-version OCC on acceptance and on capacity PATCH, admission-version OCC on back-transfer referral), 22 calculations, 15 validations in a 15-level priority ladder, 81 endpoints, 47 error codes, 7 roles with 3 segregation-of-duties rules.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2324 lines): 25 instances, distributed across all 9 rule_ids (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

`SCAFFOLD_CORNER_DESIGN.yaml` (3790 lines): all 9 required sections, 81 instances — 53 with full `test_recipe` blocks and 28 `excluded_because` stubs citing 21 distinct §1.8 instances (all citations resolve; all 106 names unique across §1.8 ∪ §1.9). Per-section: entities 10, state_machines 17 (12 live), calculations 15 (7 live), validations 11, endpoints 5 (3 live), errors 13 (3 live), rbac 3, cross_cutting_complexity_layers 6 (3 live), consistency_model 1.

## Design adjudications

- The DesignationReview `verify` path has no below-floor error code, so the below-floor case is exercised through the declared `SUBMITTED → DENIED` certify transition instead of an error assertion.
- SurveillanceReport submit/accept SoD is unreachable by role construction (submit is UnitDirector-exclusive, accept NetworkAdmin-exclusive), so `ERR_SEGREGATION_OF_DUTIES` is triggered via review submit/return, review verify/certify, and milk receive/verify — the latter proving identity is compared per person, not per role.
- `PROVISIONAL/DESIGNATED → CONDITIONAL` demotion is declared only for the equipment out-of-service path, so the credential-revocation cascade instance explicitly asserts `designation_status` is left untouched.
- `ERR_MILK_LABEL_MISMATCH` is a verification-time error, so it is triggered at `/verify` rather than at administration.
- A `TRANSPORT_ISOLETTE` is not required for LEVEL_III, so taking the isolette out of service does not abort in-flight runs; the dispatch-gate instance asserts that non-cascade explicitly.
- Error coverage was split so that every one of the 47 codes has exactly one live trigger somewhere across §1.8/§1.9; the errors section carries live triggers only for the codes no other section reaches (label mismatch / not-administrable, surge-no-staffed-capacity, not-eligible-for-followup) and defers the other ten to §1.8.
- Error-code disambiguation is load-bearing in the layers section: unit-version conflicts return `ERR_UNIT_VERSION_CONFLICT` (412) while the back-transfer referral returns `ERR_ADMISSION_VERSION_CONFLICT` (412), one instance per §1.2.1 rule using that rule's declared `write_endpoint`.

No sibling task directory was listed, globbed, grepped, or read at any point.

## Step 3: Copy shared files — 2026-09-02T21:22:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:35:00.000Z

Orchestrator anti-truncation verification (performed independently of the subagent): `PRD.md`
is 464 lines; headings are §1 Introduction, §2 Global Specifications, §3 Business Logic &
Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue; the file's last line is a
complete markdown table row (`| ERR_MILK_VOLUME_EXCEEDED | 422 |`) inside §5, i.e. it ends at
a real section boundary, not mid-sentence. 90 ERR_ mentions present. `grep -ci "harder than
expert"` → 0, so no difficulty-instruction text leaked into the PRD. No regeneration needed.

### Step 4 subagent summary (verbatim)

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport/workspace/PRD.md` — **464 lines**, last heading **`## 5. Error Code Catalogue`**, final line is the complete table row `` | `ERR_MILK_VOLUME_EXCEEDED` | 422 | ``. Not truncated: the document ends at a real section boundary with a fully-formed 47-row error table.

**Structure** (domain-derived, not copied from the example): §1 Introduction (3 paragraphs, framed from the regional-network pain points); §2 with 11 subsections — 2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, then 2.4 Resource Identity/Versioning/Logical Clock, 2.5 Derived-on-Read Status & Capacity Sweep, 2.6 OCC, 2.7 Level-of-Care Ladder, 2.8 Bed Ledger/Waterfall/Census Posture, 2.9 Precision & Rounding, 2.10 Rejection Precedence & Path Resolution, 2.11 Cascade Propagation & Segregation of Duties; §3 with 9 workflow subsections (onboarding → designation review → referral intake → acceptance/deferral → surge escalation → transport → admission/bedside/milk/infection → back-transfer/discharge/capability cascade → surveillance & follow-up); §4 with all 81 endpoints in a 4-column table; §5 with all 47 error codes in a 2-column table.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 162 required, 162 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 35 required, 35 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```
(Two passes were needed — the first pass left the 9 path-parameter identifiers only inside compound `/path/{param}` tokens in §4; a §2.10 paragraph mapping each identifier to its not-found code fixed that and simultaneously surfaced the 12 previously table-only `ERR_*_NOT_FOUND` codes.)

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (§2.10 numbered 1–15, explicit ordering), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_unit_version / expected_admission_version + error_id + 412 + version_bump_operations lists), 0 missing
- state_machines[].transitions: 8 machines / 45 transitions checked, 45 fully expressed (from/to named, every precondition paired with its error_id, every side effect stated), 0 missing
- calculations[]: 22 checked, 22 fully expressed in operator-free prose with worked figures, 0 missing
- validations[] conditions: 47 error ids checked, 47 matchable to a condition in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 81 endpoints checked, all side-effect blocks expressed, 0 missing
- entities[].fields[] structured content: 162 checked, defaults/initials/enums/derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (dispatch ground/air, submit/deny_rounds_exhausted, certify/certify_denies_below_floor, request-info/divert_info_exhausted, discharge_home/record_death, attendance/no-show, crude/device-adjusted rate, committed/forecast capacity, current_support/anticipated_need level), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1141
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional confirmations**
- `grep -ci "harder than expert"` → **0**. The scaffold's `scenario` field opens with that instruction line; it was discarded and no difficulty-instruction text leaked in.
- §2.2 was diffed byte-for-byte against `section-2.2-response-structure.md`: **VERBATIM MATCH** (placeholders `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }` all intact).
- No fuzzy quantifiers: 0 hits for "approximately", "roughly", "conservatively", "more or less", "in the neighborhood". The single "about " is "Nothing else about a unit is editable".
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**One scaffold inconsistency handled defensively:** `EquipmentAsset.out_of_service_reason` declares the enum `BIOMED_FAULT | RECALL | CONTAMINATION | AWAITING_PARTS`, while the out-of-service endpoint's own purpose text says the `reason` is `BIOMED_FAULT | RECALL | SCHEDULED_SERVICE`. The PRD documents the union of all five accepted values so neither reading can produce an unfair test failure.

## Step 5: Generate Unit Tests — 2026-09-02T22:25:00.000Z

Launched concurrently with Step 6. Note on isolation: the two Agent calls were issued in
back-to-back messages rather than one message, so strict "test_suite/ does not exist yet"
physical isolation was not guaranteed by wall-clock ordering alone. The impl-gen prompt
carried an explicit hard prohibition on reading/listing/globbing test_helpers/ and test_suite/,
and Step 6's returned summary states implementation was built from INSTRUCTION.md + SCAFFOLD.yaml
+ PRD.md only; treated as satisfied.

### Step 5 subagent summary (verbatim)

Done. Suite generated, centrally audited, collecting clean.

## Files written

**`test_helpers/` (9 files, Stage 1, written by me)**
`/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport/test_helpers/` — `types.py` (13 TypedDicts, ~30 enums, `LEVEL_RANKS`), `api_errors.py` (47 codes + `HTTP_STATUS_CODES` wired into `validate_error` via `set_error_http_status_map`), `api_client.py` (`ApiClient` with all 81 endpoint methods; empty api_prefix), `constants.py`, `factories.py`, `assertions.py` (per-entity shape checks plus the invariant checkers `assert_bed_ledger_balanced`, `assert_census_posture_consistent`, `assert_effective_level_consistent`, `assert_milk_ledger_balanced`, `assert_sweep_result`), `test_users.py` (opaque roles plus unit-scoped `<unit_id>:<person>` builders), `fixtures.py` (`setup_network()` plus ~70 step helpers), `__init__.py` (64-name barrel).

**`test_suite/` (conftest + 9 test files, Stage 2, fanned out to 9 parallel single-file agents)**
`test_01_entities_and_endpoints.py` 39, `test_02_state_machines.py` 29, `test_03_calculations.py` 19, `test_04_validations.py` 24, `test_05_errors_rbac_and_concurrency.py` 32, `test_20_dual_variant_and_formulas.py` 12, `test_21_state_machines_and_cascades.py` 10, `test_22_precedence_and_boundaries.py` 10, `test_23_dependencies_overlap_invariants.py` 16.

## Counts

- **191 tests total**, `pytest --collect-only` = 191 collected, 0 collection errors, pyflakes clean, no duplicate test names.
- **Queue A (Difficulty): 48 tests / 24 of 25 instances**, exactly 2 per instance, across all 9 rule_ids.
- **Queue B (Corner): 143 tests / 53 of 53 recipe-bearing instances** across all 9 sections (entities 29, state_machines 29, validations 24, calculations 19, rbac 16, endpoints 10, errors 7, cross_cutting 6, consistency_model 3). None of the 28 `excluded_because` stubs is tagged or translated.

## Audit (run centrally by me, not trusting subagent claims)

`python3 /tmp/audit_tests.py <task_dir>`: **0 citation failures** (every quoted PRD sentence >=25 chars is a verbatim substring of `workspace/PRD.md`), **0 tag problems** (exactly one `Design:` line per test, last line of the docstring, all resolving to non-stub instances), 0 queue-B instances uncovered, 0 queue-A instances below 2 tests, no `skip`/`xfail`/`pytest.skip`, no `scaffold` references. Tests were not executed — no server, and `workspace/implementation/` was never read or listed.

## Instances skipped (1)

- `Difficulty/priority_pair_validation_conflict/duplicate_enrollment_referential_precedes_window_temporal` — PRD §3.9 attaches `ERR_APPOINTMENT_OUTSIDE_WINDOW` only to scheduling's `confirmed_appointment_date`, so the pair's lower-priority leg (an out-of-window `target_appointment_date` at enrollment creation) is not uniquely derivable. Gap left as a gap.

## Partial omissions inside kept instances (3)

- `Corner/validations/unit_scoped_caller_cannot_act_for_another_unit` — the recipe's third refusal (body-borne foreign `unit_id` on `POST /staff-credentials`) dropped: §2.1 pins scope comparison to four specific targets that do not include it, and the companion instance requires body FKs to be resolved at priority 6 instead.
- `Corner/errors/surge_authorization_without_staffed_capacity_is_refused` — asserts the refusal plus `REQUESTED`/null `authorized_by_user_id`, not persisted `census_ratio_at_request`/`escalation_tier`/`staffing_waiver_ratio`; §3.5 never says a refused authorization writes them.
- `Corner/state_machines` — two sub-assertions dropped (`compliance_score == null` on a DRAFT review, `pre_quarantine_status == null` on a new batch) as not PRD-derivable.

## Design-data discrepancies found (PRD value asserted, per PRD-first)

1. `Corner/calculations/followup_eligibility_basis_risk_tier_and_window` asserts `triage_priority == 92.50`; §3.3 uniquely yields **82.50** for its LEVEL_III / 26.0 wk / 850 g input.
2. `Corner/entities/optional_fields_fall_back_to_declared_defaults` asserts `33.75`; §3.3 yields **38.75** for CASE-D1 (33.75 is the PRD's unrelated back-transfer worked example).
3. `Difficulty/cross_entity_state_dependency/departure_depends_on_referral_status` stabilizes with `mean_bp_mmhg: 31` at 30.0 wk (all four targets met → score 100) yet asserts `stabilization_score == 92`; the test uses the PRD's own worked example (36.8 / 60 / 28 / 92) so both asserted observables hold.

Also worth noting: PRD §2.4 renders instants with three fractional digits, so several files carry a small private instant-comparison helper rather than string-equality against `CLOCK_START`.

## Step 6: Generate Implementation — 2026-09-02T22:12:00.000Z

### Step 6 subagent summary (verbatim)

The implementation is complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport/workspace/implementation/` (flat module layout, ~3,900 lines total):

- `start.sh` — installs Flask only when missing (avoids pip contention on per-test reboots), then `exec python3 app.py`; `requirements.txt`
- `app.py` — blueprint registration, `ApiError` handler, HTTP 404/405/5xx and catch-all handlers, `app.run(host=0.0.0.0, port=$PORT or 10000)`
- Infrastructure: `db.py` (in-memory dicts + `_seq` monotonic tiebreak), `clock.py` (logical clock from `2026-08-01T00:00:00Z`), `errors.py` (all 47 error ids with the catalogue's HTTP status forced by id, so a call site can't mis-status), `response.py` (envelope, `req_` + 20 uppercase alnum ids, Decimal→float), `ctx.py` (auth/role/unit-scope/schema/pagination), `lookup.py`, `derive.py` (every formula), `serialize.py` (all computed fields derived at read time), `cascade.py` (holds, deferral promotion, capability cascade, 4-pass capacity sweep)
- Routes: `api_network.py` (clock, sweep, units, standards, credentials, assets, reviews), `api_referrals.py` (referrals, bed-reservations, transport runs), `api_care.py` (admissions, milk batches), `api_oversight.py` (surge escalations, surveillance reports, follow-up enrollments)

## Endpoint count
**81 routes**, diffed programmatically against `SCAFFOLD.yaml`: zero missing, zero extra (method + path exact match).

## Boot check
`PORT=18447 bash start.sh` booted cleanly; three further kill/relaunch cycles on a second port each returned `total_count: 0` on `GET /nicu-units` and `201` on a fresh `POST /nicu-units`, confirming per-test-server isolation with no seeded data and no on-disk state (only `__pycache__`, since removed). Envelope confirmed: `meta.api_request_id` = `req_` + 20 uppercase alnum, wall-clock `api_request_timestamp` with 3 fractional digits, `response_type` object/array/error, list meta carrying limit/offset/total_count/has_more.

Three end-to-end scenarios passed against the live server: full transport→admission→milk→back-transfer→discharge→follow-up chain (triage 71.25, stabilization 100, developmental 60.00, back-transfer `weight_basis_grams` frozen at 1600 with the GA term suppressed, milk ledger 40.0→reverse 0.0→discard 120.0); precedence and cascades (maternal-transfer preference beating `ERR_NO_BED_AVAILABLE`, OCC 412, scope 403, defer→sweep expiring a 720-minute antenatal hold and promoting the queue with `units_touched: 1`, HFOV out-of-service dropping capability to LEVEL_II, unit to CONDITIONAL and diverting the referral with `CAPABILITY_LOST`); and the review lifecycle (duplicate-standard/open-review guards, return→resubmit round counting, segregation of duties on certify, CERTIFIED at LEVEL_III → unit DESIGNATED, credential revoke dropping capability, SERVICE_DUE→IN_SERVICE, PATCH with OCC).

Two judgement calls worth flagging: the isolette guard order at activation follows §2.10's band order (not-serviceable 11 → unit-mismatch 12 → unavailable 13) rather than §3.6's prose order, and `appointment_window_end` is read as `discharged_at + 90 days` (not window_start + 90).

## Step 7: Run Tests and Iterate — 2026-09-02T22:53:00.000Z

Orchestrator-side verification (independent of the subagent's claim, per the known failure mode
where a Step 7 agent reports a clean sweep without leaving artifacts): all eight
`workspace/implementation/results.{1..8}.json` exist on disk, parse as JSON, and each reports
`passed == total == 191`, all timestamped 22:44:25. The sweep was run under `setsid nohup` so no
round was SIGTERM-reaped; `sweep.log` shows the runner's own port-registry release lines, not
`Terminated`.

### Step 7 subagent summary (verbatim)

All 8 parallel rounds are green: 191/191 in every round.

## Summary

**Iterations run:** 2 (sweep 1 → 4 consistent failures in all 8 rounds; sweep 2 → 8/8 clean at 191/191).

**Tests deleted:** none. All 4 failures traced to a real precedence-band defect in the implementation plus one assertion that over-specified a rendering the PRD is silent about; nothing asserted a scaffold-only rule.

**Fixes applied to `test_suite/`**
- `/home/ubuntu/github/CodingPRD/tasks/task_2447_neonatal_intensive_care_level_designation_transport/test_suite/test_23_dependencies_overlap_invariants.py` — `test_a_second_appointment_on_the_same_calendar_day_is_refused` and `test_moving_the_second_appointment_to_the_next_calendar_day_is_allowed` compared the echoed `confirmed_appointment_date` byte-for-byte against the literal sent (`2026-09-01T09:00:00Z` vs the server's `...00.000Z`). PRD §3.9 only requires that scheduling "records the confirmed instant", and §2.4 pins the three-fractional-digit rendering to `created_at`/`updated_at`, saying of client-supplied instants only that they "are taken as given and are not clamped to the clock" — the wire *format* of an echoed client instant is not uniquely derivable (verbatim echo vs. house-canonical rendering are both faithful readings). Per STEP 1c I kept the covered assertion (the instant recorded is the instant confirmed) and dropped the uncovered one, using instant equality via a local `_instant()` helper — the same helper convention the suite already uses in `test_03_calculations.py` for exactly this reason. The `CLINIC_DAY_FULL` / status / calendar-day assertions were left untouched.

**Fixes applied to `test_helpers/`:** none needed — no fixture, factory or role-header bug surfaced.

**Fixes applied to `implementation/`** (one defect, five call sites)
- `workspace/implementation/api_oversight.py` — `create_escalation`, `create_report`; and `workspace/implementation/api_network.py` — `create_credential`, `create_asset`, `create_review`: the unit-ownership check on a **body-supplied** `unit_id` ran before schema validation and before FK resolution, so an escalation created with an inverted window plus a non-existent `unit_id` returned `ERR_UNIT_SCOPE_VIOLATION` instead of `ERR_INVALID_REQUEST`/`ERR_UNIT_NOT_FOUND`. PRD §2.10 band 4 scopes only "the unit the operation acts on **as described in §2.1**", and §2.1's ownership enumeration is a closed list of four comparisons — path unit, referral `receiving_unit_id`, referral `referring_unit_id` (creation/withdrawal), admission `unit_id` — none of which covers escalation/review/report/credential/asset creation. For those, the only ordering PRD gives a body `unit_id` is band 5 (schema, `effective_to` strictly after `effective_from`) then band 6 ("every `id` supplied in the request body must resolve — `unit_id`, … — else the matching not-found code"). The check was moved after `lookup.unit(...)` rather than removed, so the §3.5/§3.2/§3.9 "its UnitDirector" ownership guard still refuses a foreign director acting for a unit that exists. `POST /referrals` was deliberately left at band 4, since §2.1 names referral creation explicitly.

No endpoint, field, side effect or seeded data was added; storage remains in-memory dicts.

## Step 8: Finalize PRD — 2026-09-02T22:59:00.000Z

Not skipped: Step 7 applied 1 test_suite fix and 1 implementation defect fix across 5 call sites.

### Step 8 subagent summary (verbatim)

Done. `PRD_FINALIZED.md` written with three surgical edits.

## Size
- `PRD.md`: 464 lines / 111,611 bytes → `PRD_FINALIZED.md`: 464 lines / 113,562 bytes.
- Line delta: **0 lines (0.0%)** — all edits are inline within existing paragraphs. Byte delta: **+1,951 (+1.75%)**.

## Changes (one bullet each)
- **§2.1** — *insert* — added the body-supplied `unit_id` case to the closed ownership enumeration: for a credential, equipment asset, designation review, surge escalation or surveillance report creation, the `X-User-ID` unit prefix must equal the body `unit_id` — `api_network.py:223, 290, 382`; `api_oversight.py:37, 159`.
- **§2.10 band 4** — *insert* — pinned *when* the ownership comparison happens: at band 4 for path-named/path-resolved units; but for a unit learned from the body (the five creations above, plus `POST /admissions` via the body `referral_id`'s `receiving_unit_id`) it runs after band 5 schema and band 6 body-id resolution and before band 7, so an inverted window or an unresolvable `unit_id` yields `ERR_INVALID_REQUEST` / `ERR_UNIT_NOT_FOUND` rather than `ERR_UNIT_SCOPE_VIOLATION`; `POST /referrals` stays at band 4 for a string `referring_unit_id`, falling through to band 5 when the field is absent or non-string — `api_oversight.py:33-37, 155-159`; `api_network.py:217-223, 284-290, 378-382`; `api_care.py:32-35`; `api_referrals.py:24-26`.
- **§2.4** — *insert* — pinned the wire rendering of client-supplied instants: every instant returned (server-stamped, derived or client-supplied) is rendered ISO 8601 UTC with exactly three fractional digits, normalised to UTC and shown to whole milliseconds, not echoed verbatim; the stored value used for comparisons stays exactly as supplied — `clock.py:30-38` (`fmt`), `serialize.py` (all instant fields via `ts`), `api_network.py:28` (`current_utc`).

## Per-edit pre-edit search log
**Edit 1 (§2.1)** — (a) Subject: which unit a unit-scoped caller's `X-User-ID` prefix is compared against. (b) Enumerated/read every `ctx.require_scope` callsite: `patch_unit` (path unit), `revoke_credential`, `service_asset`, `out_of_service_asset`, `submit_review`, `stand_down_escalation`, `submit_report` (unit recorded on the path entity), `create_credential`/`create_asset`/`create_review`/`create_escalation`/`create_report` (body `unit_id`), `create_referral` (body `referring_unit_id`), `request_info`/`accept`/`decline`/`defer`/`revoke_acceptance` (referral `receiving_unit_id`), `provide_info`/`withdraw` (referral `referring_unit_id`), `create_admission` (referral `receiving_unit_id`), `infection_event`/`back_transfer_ready`/`back_transfer_referral`/`discharge` (admission `unit_id`); plus `ctx.require_scope` itself (no-op for GET and for non-unit-scoped roles) and a scripted sweep confirming **every** mutating endpoint whose role list contains a unit-scoped role calls `require_scope`, and none that doesn't. (c) Adjustment: I first also added a clause covering entity-addressed actions (revoke credential, submit review, stand down, …) and then **removed** it — accurate, but outside the Step 7 diff's scope. The committed clause only adds the five body-`unit_id` creations, leaving the existing enumeration verbatim so nothing about the other paths is narrowed or claimed exhaustive.

**Edit 2 (§2.10 band 4)** — (a) Subject: the precedence position of the unit-scope check relative to bands 5/6/7. (b) Enumerated the same full `require_scope` list and read the statement order in each handler, confirming path-named/path-resolved units are compared before `ctx.body()`; confirmed the five creations compare after full field validation *and* after `lookup.unit`; confirmed `create_admission` compares after `req_string("referral_id")` + `lookup.referral`; confirmed `create_referral` compares before any `ctx.req_*` and before both `lookup.unit` calls, guarded by `isinstance(..., str)`; checked `revoke_acceptance`/`withdraw`/`back_transfer_referral` to be sure no path-addressed endpoint defers its scope check past the body; cross-read `test_04_validations.py:200-241` as auxiliary evidence. (c) Adjustment: widened the sentence from "a body `unit_id`" to also name the `referral_id` → `receiving_unit_id` route used by `POST /admissions`, which the Step 7 note never mentions but which the impl exhibits; and added the explicit absent/non-string fallback for `referring_unit_id` so the band-4 exception is not over-claimed.

**Edit 3 (§2.4)** — (a) Subject: how instants appear on the wire. (b) Enumerated every instant-valued output: all `ts(...)` uses in `serialize.py` (unit, standard `created_at`; credential `expires_on`/`revoked_at`; asset `last_service_at`/`next_service_due_at`/`out_of_service_at`/`decontamination_ready_at`; review `assessment_at`; reservation `held_at`/`expires_at`; run `depart_at`/`planned_return_at`/`arrived_at`; admission `infection_confirmed_at`/`discharged_at`; batch `expressed_at`/`expires_at`; escalation `effective_from`/`effective_to`; report `period_start`/`period_end`/`submitted_at`; enrollment `target_appointment_date`/`confirmed_appointment_date`/window bounds/`attendance_recorded_at`), `api_network.py:28` (`current_utc`), `response.py:20` (`meta.api_request_timestamp`), `response.py:27` (`clean` — no raw datetime ever escapes), `cascade.py:201` (sweep returns integers only), and `clock.parse_dt`/`fmt` (UTC normalisation on ingest, millisecond truncation on render, full precision retained in storage). (c) Adjustment: scoped the claim to *rendering* only and added "while the instant retained for every comparison and every derivation is exactly the one supplied", so the sentence cannot be read as clamping or rounding stored values — `fmt` truncates only the display, and window/expiry comparisons elsewhere use the stored instant. Also phrased it as covering *every* returned instant (not just `confirmed_appointment_date`) because the impl is uniform, and left §2.2's `api_request_timestamp` wording untouched since it already agrees.

## Step 9: Complete PRD — 2026-09-02T23:20:00.000Z

Orchestrator-side verification: `PRD_COMPLETED.md` is 464 lines / 127,664 chars, retains all five
top-level sections (§1–§5), ends on the complete final table row `| ERR_MILK_VOLUME_EXCEEDED | 422 |`
inside §5 — i.e. not truncated. `grep -ci "harder than expert"` → 0. All eight
`workspace/implementation/results.{1..8}.json` remain on disk at 191/191, unchanged by Steps 8–9
(both of which touched only PRD copies, never `implementation/`), so no re-sweep was needed.

Pipeline complete: Steps 1–9 all executed, no step skipped.

### Step 9 subagent summary (verbatim)

Done. `PRD_COMPLETED.md` is written, complete, and ends at the final error-catalogue row.

## File deltas
- Source: `workspace/PRD_FINALIZED.md` — 464 lines, 113,562 chars
- Output: `workspace/PRD_COMPLETED.md` — 464 lines, 127,664 chars (**+14,102 chars**, 59 paragraphs touched, no lines added or removed, no new sections)
- Tail verified: last line is `| `ERR_MILK_VOLUME_EXCEEDED` | 422 |` — table intact.

## Counts
- **60 ambiguity-pins**, **11 mismatch-revisions** (71 pinned behaviors across 68 edits)

## Cross-checks that needed no change
- §5 catalogue: all 47 codes and statuses match `errors.py:14-62` exactly (`STATUSES` is authoritative over call-site statuses, so `ERR_MILK_LABEL_MISMATCH` at 409 as documented).
- §4 table: all 81 method/path rows and all 81 role lists match the blueprints exactly.

## Changes
- §2.1 — revise — ambiguity — whitespace-only auth headers are unauthenticated, not just absent/empty — ctx.py:48
- §2.1 — insert — ambiguity — unit scope guards mutations only; a GET never yields `ERR_UNIT_SCOPE_VIOLATION` — ctx.py:55-57
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics — response.py:13-14
- §2.2 — insert — ambiguity — `api_request_timestamp` reads real wall-clock, not the logical clock — response.py:20
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty-string pagination/filter params treated as omitted — ctx.py:220-243
- §2.3 — revise — ambiguity — identical-`created_at` rows held in insertion order — db.py:63
- §2.3 — revise — **mismatch** — deferral-queue read returns every `DEFERRED` referral, including over-level ones promotion skips — api_network.py:145
- §2.3 — insert — ambiguity — `has_more` = offset + rows returned < `total_count` — response.py:57
- §2.4 — revise — ambiguity — clock endpoint requires `current_utc`, returns a bare single-key object — api_network.py:26-28
- §2.5 — revise — ambiguity — sweep `unit_id` is a body field that must resolve; narrows passes 1-2 by `unit_id`, pass 3 by `clinic_unit_id` — api_network.py:36-37, cascade.py:150/169/188
- §2.5 — insert — ambiguity — pass 1 diverts the referral only while still `ACCEPTED` — cascade.py:159
- §2.5 — insert — ambiguity — `units_touched` counts only passes 1-2; enrollment-only sweep reports 0 and bumps no version; pass 4 adds none — cascade.py:139-146,195-199
- §2.6 — revise — ambiguity — the version field is an integer — api_referrals.py:144
- §2.7 — insert — ambiguity — a level with no declared standard is not a `capability_level` candidate — derive.py:199-207
- §2.7 — insert — ambiguity — both compliance booleans read true when no standard exists for `designated_level` — derive.py:214-227
- §2.8 — insert — ambiguity — a level with no declared standard contributes 0 to `required_nurse_count` — derive.py:274-284
- §2.8 — insert — ambiguity — capacity-projection `data` is a bare 8-key object, no id/timestamps/version — api_network.py:128-137
- §2.10 band 5 — insert — ambiguity — non-object JSON body fails as malformed; unknown path/method → `ERR_INVALID_REQUEST` at 404/405 — ctx.py:71, app.py:31-41
- §2.10 band 6 — insert — ambiguity — two body ids resolve in declaration order; referral creation resolves `referring_unit_id` first — api_referrals.py:36-37
- §3.1 — revise — ambiguity — `staffed_bed_target`/`annual_admission_volume`/`followup_clinic_daily_capacity` are integers with stated minima — api_network.py:50-54
- §3.1 — insert — ambiguity — `expected_unit_version` is the patch's only required field; version advances even with no editable field — api_network.py:101-116
- §3.1 — insert — ambiguity — credential revocation allowed from any derived status; unit version advances only when `effective_level` fell — api_network.py:260-274
- §3.1 — insert — ambiguity — service/out-of-service allowed from any status; servicing writes nothing to the unit — api_network.py:331-342
- §3.2 — insert — ambiguity — submission at a suspended unit → `ERR_DEPENDENT_STATE_INVALID` (409); rounds-exhausted branch evaluated first — api_network.py:444-458
- §3.2 — insert — ambiguity — with no standard for `requested_level`, all subscores and score are 100.00 and both thresholds 0 — derive.py:450-460,506-510
- §3.2 — revise — ambiguity — verify below floor → `ERR_INVALID_STATE` (409), after status check, before SoD — api_network.py:496-500
- §3.2 — revise — ambiguity — one rung below `LEVEL_I` is `LEVEL_I`, so a sub-minimum `LEVEL_I` request certifies `DESIGNATED` — api_network.py:532-545
- §3.2 — insert — ambiguity — a `SUBMITTED` review at/above floor cannot be certified → `ERR_INVALID_STATE` (409) — api_network.py:515-518
- §3.3 — revise — ambiguity — `birth_weight_grams` is a whole number — api_referrals.py:32
- §3.3 — revise — ambiguity — rounds-exhausted request-info discards `requested_items` (left null); empty provide-info body is valid and consumes a round — api_referrals.py:94-132
- §3.4 — insert — **mismatch** — acceptance checks run in §2.10 band order: version, own state, level, suspension, maternal, bed last — api_referrals.py:144-174
- §3.4 — revise — ambiguity — acceptance clears a prior `decision_reason` to null — api_referrals.py:176-177
- §3.4 — revise — ambiguity — `reservation_id` fallback is the latest `held_at` among all reservations, `RELEASED` and `EXPIRED` alike — derive.py:420-427
- §3.4 — insert — ambiguity — deferral with a bed still free → `ERR_DEPENDENT_STATE_INVALID` (409) — api_referrals.py:208-210
- §3.4 — insert — ambiguity — revocation leaves `decision_reason` untouched — api_referrals.py:255
- §3.5 — insert — ambiguity — the four authorization outputs are null until authorization; a refusal writes none — api_oversight.py:45-48,101-104
- §3.5 — insert — **mismatch** — window-overlap test precedes the ratio/tier/bed arithmetic — api_oversight.py:86-99
- §3.6 — insert — ambiguity — `crew_composition` is any string array, not enum-checked — api_referrals.py:308
- §3.6 — insert — ambiguity — the reservation's own status is not examined at activation — api_referrals.py:315
- §3.6 — revise — **mismatch** — serviceability is tested before the unit-ownership check — api_referrals.py:318-322
- §3.6 — revise — **mismatch** — only `ABORTED` runs leave the isolette test; an `ARRIVED` run holds it to `arrived_at` + decon — api_referrals.py:327-334, derive.py:563-569
- §3.6 — revise — **mismatch** — one body-less dispatch endpoint reads `mode` off the run; no mode-mismatch error exists — api_referrals.py:384-401
- §3.6 — revise — **mismatch** — air dispatch order is crew → isolette → weather — api_referrals.py:389-399
- §3.6 — revise — ambiguity — all four stabilization values required on every posting, accepted unbounded — api_referrals.py:426-429
- §3.6 — revise — **mismatch** — departure checks the referral's state before the stabilization bundle — api_referrals.py:455-462
- §3.6 — revise — ambiguity — `arrived_at` is taken as given, need not follow `depart_at` — api_referrals.py:467
- §3.6 — insert — ambiguity — abort returns only a still-`ACCEPTED` referral to `PENDING` and does not advance the unit's version — api_referrals.py:481-499
- §3.7 — revise — ambiguity — `transport_run_id` = latest `ARRIVED` run by `created_at` on the referral's live `HELD` hold; null with no live hold — api_care.py:40-45
- §3.7 — revise — ambiguity — care update: weight integer >=1, both booleans default false, terminal care statuses refused `ERR_INVALID_STATE` — api_care.py:133-137
- §3.7 — revise — ambiguity — developmental round: all four fields required, minutes integers >=0, same terminal refusal — api_care.py:157-162
- §3.7 — revise — ambiguity — CONFIRM_CLABSI without a line day → `ERR_INVALID_STATE` (409) — api_care.py:197-199
- §3.7 — revise — ambiguity — RESOLVE restores a null `pre_quarantine_status` to `RECEIVED`, then re-derives — api_care.py:208-210
- §3.7 — insert — ambiguity — receiving milk never examines the admission's `care_status` — api_care.py:360
- §3.7 — revise — ambiguity — verification requires exactly `RECEIVED` (`ERR_INVALID_STATE`) before label, then SoD — api_care.py:409-414
- §3.7 — revise — **mismatch** — a stored `QUARANTINED` outranks the administered/partially-administered arms — derive.py:628-645
- §3.7 — insert — **mismatch** — administration guards run admission → administrability → expiry → volume — api_care.py:421-444
- §3.7 — insert — ambiguity — reversal is guarded by volume alone: no batch status, expiry or admission check — api_care.py:446-464
- §3.7 — revise — ambiguity — discard `reason` validated but not stored; clears `pre_quarantine_status`; only already-`DISCARDED` refused — api_care.py:472-479
- §3.8 — revise — ambiguity — support-modality and infection failures are `ERR_INVALID_STATE`; bundle gate evaluated first — api_care.py:223-232
- §3.8 — revise — ambiguity — back-transfer referral copies GA/birth weight/support, opens with empty `diagnoses` and `planned_surgery` false, answers 201 with the referral — api_care.py:255-291
- §3.8 — insert — ambiguity — releasing a superseded referral's hold does not advance that unit's version — api_care.py:286-288
- §3.8 — revise — ambiguity — `back_transfer_source_admission_id` written whenever the source resolves; the source moves only from the two back-transfer statuses — api_care.py:56,88-97
- §3.8 — insert — ambiguity — unsettled milk at HOME discharge → `ERR_DEPENDENT_STATE_INVALID` (409), after the own-state check — api_care.py:305-313
- §3.8 — insert — ambiguity — the DECEASED branch does not re-derive `high_risk_graduate` — api_care.py:315-324
- §3.8 — insert — ambiguity — out-of-service always advances the unit's version, whether or not `effective_level` fell — api_network.py:345-365
- §3.9 — revise — ambiguity — a report opens with every metric already computed — api_oversight.py:163-177
- §3.9 — revise — ambiguity — incomplete submission without ack → `ERR_INVALID_STATE` and nothing written; submitter stored but not exposed; acceptance bumps unit version only when `quality_flag` changes — api_oversight.py:210-238, serialize.py:259
- §3.9 — insert — ambiguity — `eligibility_basis`/`risk_tier` re-derived from the admission on every read and filter — serialize.py:283-296
- §3.9 — insert — ambiguity — an invalid clinic → `ERR_DEPENDENT_STATE_INVALID` (409), evaluated after the eligibility gate — api_oversight.py:275-278
- §3.9 — revise — **mismatch** — `appointment_window_end` is `discharged_at` + 90 days, not window start + 90 — api_oversight.py:292-293
- §3.9 — insert — ambiguity — a clinic with capacity 0 is never schedulable — api_oversight.py:346-351

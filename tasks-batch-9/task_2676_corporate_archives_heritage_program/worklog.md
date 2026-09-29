# Worklog — task_2676_corporate_archives_heritage_program

## Step 1: Create task directory — 2026-09-04T05:10:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2676_corporate_archives_heritage_program and its workspace/ subdirectory (pre-assigned path from orchestration args; no index scan performed).

## Step 2: Generate scaffold — 2026-09-04T06:55:00.000Z

All three scaffold artifacts for task 2676 are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2676_corporate_archives_heritage_program/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3868 | 179,782 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1979 | 129,640 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5501 | 334,118 |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys leaked in; each design file carries exactly one top-level key.

**§1.0–§1.7 counts:** 17 entities, 16 state machines (incl. the two parallel `OralHistoryInterview#consent_status` / `#transcription_status` axes), 2 OCC concurrency rules, 13 calculations, 36 priority-ordered validations, **88 endpoints**, 66 error codes, 7 roles. Profile: `compliance_audit` / `access_control_matrix`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, temporal_windowing]`.

**§1.8 — 9 difficulty rules, 23 instances:** `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (3), `transitive_cascade` (3), `priority_pair_validation_conflict` (2), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (2).

**§1.9 — all 9 guide sections, 118 instances (87 with full test recipes, 31 `excluded_because` stubs):** entities 15, state_machines 23 (16 real), calculations 19 (8 real), validations 29 (20 real), endpoints 6, errors 12 (10 real), RBAC 7, cross-cutting complexity layers 6 (4 real), consistency model 1.

**Verification performed**
- `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (997 calls scanned across both design files).
- All 66 error codes are asserted *positively* somewhere. This caught two real defects: `ERR_PRESERVATION_BUDGET_EXCEEDED` and `ERR_RISK_THRESHOLD_REQUIRES_REDACTION` appeared in §1.8 only as `error_id != …` losers of priority contests, so I replaced two planned stubs with real triggers (second job one cent over a 20999 budget → 422; MEDIA 45 + CONFIDENTIAL 35 = post_screen 80 >= 75 on FULL approval → 422) and corrected the two §1.9 validation stubs whose rationales had claimed that coverage.
- Instance names unique across the union of both files; every `excluded_because.difficulty_instance` resolves to an existing §1.8 instance; every `calculations.*` / `entities.*` / `state_machines.*` grounds reference resolves (one typo fixed: `preservation_budget_position` -> `preservation_budget_conservation`).
- One §1.1 edit was needed earlier to keep a §1.9 assert defensible: `ERR_ACCESSION_STATE_INVALID`'s condition now also names the `POST /finding-aids/{id}/submit-review` parent-status case.

## Step 3: Copy shared files — 2026-09-04T06:56:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2676_corporate_archives_heritage_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T07:12:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **520 lines / 110,934 bytes**, written via chunked `cat >>` appends. `tail` confirms it ends at a real boundary: the final row of the §5 error table (`ERR_PRESERVATION_BUDGET_EXCEEDED` / `422`), no truncation. Orchestrator independently verified the tail and the section list.

The two withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC / 2.2 API Response Structure / 2.3 Pagination / 2.4 Resource Identity, Audit Fields and the Immutable Configuration Row / 2.5 The Logical Archive Clock / 2.6 Rejection Precedence Across the Rule Ladder / 2.7 Stale-Version Guards on Creation of Superseding Children / 2.8 Cascade Discipline and Immediate Reconciliation / 2.9 Segregation of Duties Within a Role / 2.10 Money, Units and Numeric Precision / 2.11 Environmental Standards for Storage Zones
- §3 Business Logic & Workflows — 3.1 Retention Schedules, Series Register and Disposal / 3.2 Appraising Historical Value / 3.3 Legal Hold Coordination and the Suspension Cascade / 3.4 Accession Processing, Provenance and the Custody Register / 3.5 Arrangement, Finding Aids and the Revision Cycle / 3.6 Preservation Planning, Format Migration and Zone Capacity / 3.7 Access Policy, Confidentiality Screening and Service Fees / 3.8 The Heritage Programme: Brand Evidence, Oral History and Exhibits / 3.9 Deaccession: Dual Clearance, Approval Cascade and Disposal Routes
- §4 API Endpoint Definitions (88-row table)
- §5 Error Code Catalogue (66-row table)

**Coverage confirmation:** 17/17 entities, 88/88 endpoints, 36/36 validations, 13/13 calculations, 66/66 errors, 7/7 roles. Mechanically verified: all 87 state-machine transitions' source/target states present, all enum values of every enum-typed field present verbatim, all 66 `errors[].id` present, all 7 `roles[].name` present, all 88 paths present in §4.

**Hard Contract reports:** Field coverage PASS (160/160 distinct field names, request bodies, query params). Rule coverage PASS (36/36 validations as a priority ladder with error id + HTTP status + applies_to; 2/2 OCC rejections; 87/87 transitions; 13/13 calculations with constants embedded; 88 endpoints' side effects; 180/180 structured field facts reconstructible; 12/12 sibling-branch symmetry groups with equal prose density). Path purity PASS (0 `/`-leading tokens, 0 bare HTTP-method tokens, 0 method+path tokens in §3). §2.2 byte-identical to the canonical response-structure fragment; zero fuzzy words and zero pseudocode operators in §1–§3.

Two internal scaffold inconsistencies were resolved by taking the broader endpoint-level reading and are documented that way in the PRD: accession rejection is declared from both `RECEIVED` and `PROVENANCE_VERIFIED` (state_machines lists only the former), and a requester revision supersedes screenings in both `OPEN` and `COMPLETED` (the endpoint lists only `OPEN`).

## Step 6: Generate implementation — 2026-09-04T07:44:00.000Z

The implementation is complete, smoke-tested, and the smoke server has been killed (port 18676 free).

## Files written
`workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` | 1 |
| `app.py` (blueprint registration, `ApiError`/400/404/405/500 handlers, `0.0.0.0:$PORT` default 10000) | 76 |
| `core.py` (logical clock, in-memory `Store`, `register`/`touch`/`serialize`) | 200 |
| `errors.py` (full error catalogue + HTTP status map) | 151 |
| `response.py` (`meta`/`response_type`/`data` envelope, offset pagination) | 101 |
| `middleware.py` (`X-User-ID`/`X-User-Role`, `endpoint(roles)` decorator) | 60 |
| `validation.py` (rung-3 shape helpers + all declared enums) | 141 |
| `services/calc.py` (all 13 calculations) | 366 |
| `services/lookup.py` (existence lookups, counter recomputation) | 158 |
| `routes/config.py` | 447 |
| `routes/custody.py` | 368 |
| `routes/preservation.py` | 251 |
| `routes/access.py` | 408 |
| `routes/heritage.py` | 348 |
| `routes/deaccession.py` (proposals + `POST /_clock/set_current_utc`) | 229 |

Total 3315 lines. Storage is in-memory dicts only; nothing is seeded at boot.

## Endpoint coverage
**88/88.** Machine-diffed the PRD §4 endpoint table against Flask's URL map: zero missing, zero extra.

## Smoke verification (PORT=18676)
Two end-to-end scripted flows (63 assertions, 0 failures) covering: auth 401/403, the full custody chain, finding-aid review/publish, appraisal screen+finalize, trademark certification, preservation plan -> migration job approve/start/complete with budget movement and auto-SATISFIED, access request -> screening -> redacted approval -> close, interview two-axis state machine with embargo, exhibit loan buffer conflict / window-not-open / check-out / return, deaccession fork-join with SoD and the 3-hop staleness cascade, legal-hold activate/release round trip, pagination bounds, and 404/405/malformed-JSON handling.

Hand-checked calculations against PRD prose, all exact: appraisal 85.00/67.00 and the clamp-to-0 case with the 0.80 provenance multiplier; migration waterfall at all three subtotal tiers (216000->0.11->192240->9000->40248->241488; 336000->...->345005; 72000->0.06->...->75264); MEDIA access fee 26658 via per-line rounding at the 7.5% tier; coverage 1.30% / max_gap_years 71 / GAP_EXCEEDED; closed-interval zone capacity rejecting touching windows at ceiling 1; unit conservation 4 = 0 + 0 + 4 after deaccession execute.

## PRD ambiguities resolved
- **Version bumps are idempotent per request** — `touch()` advances a given row's `version` at most once per HTTP call (PRD §2.8 lists rows bumped, not counter moves).
- **Everything reads the logical clock**, including `created_at`, `updated_at` and `meta.api_request_timestamp`; `_seq` breaks `created_at` ties in every ordering. Output instants normalised to 3-fractional-digit `...Z`.
- **Appraisal finalize** — rung 15 fires only for `SUSPENDED`/`legal_hold_active`; a series in another non-`ACTIVE` state still finalises but only `current_appraisal_id` changes.
- **Migration approve with a non-`ACTIVE` plan** -> `ERR_PLAN_STATE_INVALID`.
- **Dispose with an `ON_LOAN` item** -> `ERR_ITEM_STATE_INVALID`, checked after rung 19.
- **Revise with an unknown item id** -> `ERR_ARCHIVAL_ITEM_NOT_FOUND`, after rung 21 and before rung 22.
- **Screening create over a request not in `SCREENING`** -> `ERR_REQUEST_STATE_INVALID`.
- **Deaccession approve** checks item-not-`ACCESSIONED` as `ERR_ITEM_STATE_INVALID` last, after all five declared checks.
- **Certify with zero qualifying evidence** writes nothing at all — no field set, no version bump.
- **Publish** reads the stored `stale_item_count`; **deaccession execute** does not refresh finding-aid counters (literal §3.9).
- Required strings with no declared bounds use min length 1; `recipient_repository` is exempt so rung 27 can report emptiness as 422. Its value is recorded on the item as the non-serialised key `_recipient_repository`.
- `min_appraisal_score_for_permanent` is quantized half-up to 2dp on store.

## Step 5: Generate unit tests — 2026-09-04T08:46:00.000Z

Test infrastructure and suite are complete, audited, and collecting cleanly.

## Files written (task root, nothing under `workspace/`)

`test_helpers/` — 9 files, 2480 lines: `__init__.py` 88, `api_client.py` 402, `api_errors.py` 180, `assertions.py` 227, `constants.py` 128, `factories.py` 450, `fixtures.py` 758, `test_users.py` 78, `types.py` 169.

`test_suite/` — 18 files, 6740 lines:

| queue | file | lines | tests |
|---|---|---|---|
| A | conftest.py | 21 | - |
| A | test_appraisal_variants.py | 164 | 4 |
| A | test_cost_and_fee_formulas.py | 248 | 6 |
| A | test_lifecycle_transitions.py | 214 | 6 |
| A | test_cascades.py | 210 | 6 |
| A | test_rejection_precedence.py | 138 | 4 |
| A | test_boundaries.py | 267 | 6 |
| A | test_cross_entity_state.py | 263 | 6 |
| A | test_temporal_overlap.py | 229 | 4 |
| A | test_conservation.py | 203 | 4 |
| B | test_entities.py | 616 | 15 |
| B | test_state_machines.py | 836 | 16 |
| B | test_calculations.py | 452 | 8 |
| B | test_validations.py | 1043 | 20 |
| B | test_endpoints.py | 404 | 6 |
| B | test_errors.py | 629 | 10 |
| B | test_rbac.py | 443 | 7 |
| B | test_layers.py | 360 | 5 |

**133 tests: 46 queue A + 87 queue B.** `pytest --collect-only` from the task root collects 133, `compileall` clean.

## Coverage audit (programmatic, against both yamls)

141 design instances -> 110 non-stub / 31 stubs. **110 of 110 non-stub instances have >=1 `Design:` tag; 0 unknown tags; 0 tags on stubs; every difficulty instance has >=2 tests.** 403 PRD citations verified verbatim (whitespace-normalised grep) *and* verified to sit in the section each cites — that second check caught and fixed **26 wrong section numbers**. Two dead imports also removed.

## Skipped instances (all 31 are `excluded_because` stubs — no instance was skipped by the generator's own judgement)

`Corner/state_machines` 7, `Corner/calculations` 11, `Corner/validations` 9, `Corner/errors` 2, `Corner/cross-cutting complexity layers` 2. The difficulty design has no stubs.

## Assertions narrowed or corrected against the PRD (design was wrong; tests follow the PRD)

- `errors_certify_twice...`: design claims coverage 50.00 / max_gap 3 / CERTIFIED. §3.8 arithmetic gives span 9, max_gap 5, coverage 22.22 -> REJECTED / `GAP_EXCEEDED`. Asserted the PRD values; `ERR_PACKAGE_STATE_INVALID` still fires from the terminal state.
- `layers_occ_correct_version...`: dropped the design's `RecordSeries.version == 2`. §3.2 says appraisal *creation* also increments the series version, so 2 is not uniquely derivable; the appraisal's own 1->2->3, both 34.00 scores, PERMANENT and `current_appraisal_id` are all asserted.
- Undeclared enum values substituted: `target_format: BORN_DIGITAL` -> `PRESERVATION_TIFF` (§3.6 allows only TIFF/WAV/MKV), `transfer_instrument: "GIFT"` -> `DEED_OF_GIFT`.
- **PAPER-only-zone hazard, 3 recipes** (ERR-06, ERR-09, CM-01) plus the earlier VAL-15: an at-risk census of 0 sends a plan straight to `SATISFIED` (§3.6), and job approval requires `ACTIVE` with no ladder rung pinning a code. Added a FILM container to each zone so the plan stays `ACTIVE`; all asserted costs/ledger figures are unchanged.
- Earlier narrowings still in force: dropped `post_screen_risk_score == null` on the revision-cycle instance, `brand_heritage_counted is null` on the appraisal-variant instance, and the pre-processing custody claim that contradicted §3.4; `meta["total"]` does not exist (only `total_count`).

Orchestrator verification: `test_helpers/` (9 .py) and `test_suite/` (18 .py) are at the task root; `find workspace -maxdepth 2 -type d -name 'test_*'` returns nothing, so no stray test dirs landed under workspace/.

## Test/fix iteration loop (diagnostic pass)

Two 8-round parallel stability sweeps (`per-test-server` isolation, 133 tests, 8 concurrent rounds under `setsid nohup`).

**Sweep 1** — 126/133 in all 8 rounds. 7 failures, byte-identical across every round (no flakiness, no load-induced noise). All 7 traced to test-artifact bugs in three classes; **zero implementation defects, zero deletions.**

**Sweep 2** — 133/133 in all 8 rounds. Clean.

### Fixes applied to `test_suite/` (all STEP 2 "test is wrong", each made *more* faithful to PRD)

1. **Instant rendering missing its three fractional digits (4 tests).** PRD §2.4 renders API instants as "an ISO 8601 UTC instant with three fractional digits (for example `2025-05-24T10:30:00.123Z`)"; §2.2 repeats it for `api_request_timestamp` and §2.10 pins comparisons at millisecond resolution. The implementation renders every instant that way uniformly, and `test_helpers/constants.py` already carried `DEFAULT_CLOCK_MS` / `test_boundaries.py` already used `.000Z` — so the convention was established and these literals were simply un-converted.
   - `test_conservation.py`: `CHECK_OUT_INSTANT` `2026-08-15T00:00:00Z` -> `.000Z` (asserted against `checked_out_at` and `returned_at`, both §2.5 clock stamps). Fixes `test_check_out_moves_exactly_the_loan_units_off_the_shelf` and `test_return_restores_the_custody_triple_but_not_the_condition_grade`.
   - `test_temporal_overlap.py`: `L1_RECOVERY` -> `.000Z` and the inline `2026-10-16T00:00:00Z` -> `.000Z` (asserted against the derived `recovery_until` of §3.8). Fixes `test_a_window_falling_inside_the_light_recovery_buffer_still_conflicts` and `test_touching_the_front_and_starting_at_the_recovery_end_are_both_accepted`.
   - Only `L1_RECOVERY` is also used as a *window input*; `.000Z` parses to the identical instant, so the recovery-end boundary semantics are unchanged.

2. **A create asserted 200 instead of 201.** `test_endpoints.py::test_a_zone_round_trips_through_create_single_read_and_filtered_list` wrapped both `create_storage_zone` calls in `ok()` (200). PRD §4: "Resource creation endpoints return HTTP `201` on success." Switched to `created()` and added the `created` import. A suite-wide grep confirmed these were the only two mis-wrapped creates and that no non-create action is wrapped in `created()`.

3. **Setup issued a request inconsistent with PRD.** `test_errors.py::test_a_draft_finding_aid_cannot_skip_review_and_publish` built its finding aid with `arrangement_level="SUBSERIES"`. PRD §3.5 declares exactly `COLLECTION`, `SERIES`, `FILE`, `ITEM`, and §2.6 rung 3 requires "every enum value a declared member of its set" — so the PRD-faithful implementation *correctly* answered `ERR_INVALID_REQUEST` and the setup never reached the assertion. Changed to `SERIES` (incidental to this test, which is about publishing from `DRAFT`). `SUBSERIES` appeared exactly once in the suite.

4. **Factory called with a duplicated argument.** `test_entities.py::test_record_series_create_without_a_schedule_reference_is_invalid` passed `retention_schedule_id` both positionally and as `retention_schedule_id=None`, raising `TypeError: record_series_payload() got multiple values for argument 'retention_schedule_id'` before any HTTP call was made. Rewritten to build the full valid payload and `del` the one required key, so §2.6 rung 3 is the sole rule that can fire. Verified the implementation validates the field's presence (`vid`) ahead of resolving it (`fetch`), so the expected `ERR_INVALID_REQUEST` (400) beats `ERR_RETENTION_SCHEDULE_NOT_FOUND` (404) as rung 3 requires.

### Fixes applied to `test_helpers/`
None required. No shared fixture, factory or role-header helper violated a PRD precondition.

### Fixes applied to `implementation/`
None. No implementation defect was found; storage remains in-memory only and nothing is seeded at startup.

### Tests deleted
None. Every failing test's rule was verbatim in PRD and uniquely derivable; all 7 were defects in the test artifact itself. 133 tests collected before and after.

## Step 7: Run tests and iterate — 2026-09-04T09:17:00.000Z

Done. All 133 tests pass in all 8 parallel rounds.

## Summary

**Iterations run: 2**

- **Sweep 1** — 126/133 in every one of the 8 rounds. 7 failures, byte-identical across all rounds (no flakiness, no load-induced noise, no reaping).
- **Sweep 2** — **133/133 in all 8 rounds.** Clean.

**Tests deleted: none.** Every failing test's rule was verbatim in the PRD *and* uniquely derivable. All 7 failures were defects in the test artifact itself, so STEP 1 never triggered a deletion. 133 tests collected before and after.

**Fixes applied to `test_helpers/`: none.** No shared fixture, factory, or role-header helper violated a PRD precondition.

**Fixes applied to `implementation/`: none.** No implementation defect was found. The implementation was already PRD-faithful on all 7 points; in three of the four failure classes it was actively *correct* to reject what the test sent.

**Fixes applied to `test_suite/`** — all STEP 2 "test is wrong", each made the test *more* faithful to the PRD:

1. **Instant rendering missing its three fractional digits (4 tests).** PRD §2.4 renders API instants as "an ISO 8601 UTC instant with three fractional digits (for example `2025-05-24T10:30:00.123Z`)"; §2.2 repeats it and §2.10 pins comparisons at millisecond resolution. Notably `test_helpers/constants.py` already carried `DEFAULT_CLOCK_MS` and `test_boundaries.py` already used `.000Z` — the convention was established and these literals were simply un-converted.
   - `test_conservation.py`: `CHECK_OUT_INSTANT` -> `2026-08-15T00:00:00.000Z` (asserted against `checked_out_at` / `returned_at`, both §2.5 clock stamps).
   - `test_temporal_overlap.py`: `L1_RECOVERY` and an inline literal -> `.000Z` (asserted against §3.8's derived `recovery_until`). `L1_RECOVERY` doubles as a window *input*; `.000Z` parses to the identical instant, so boundary semantics are unchanged.

2. **A create asserted 200 instead of 201.** `test_endpoints.py::test_a_zone_round_trips...` wrapped both `create_storage_zone` calls in `ok()`. PRD §4: "Resource creation endpoints return HTTP `201` on success." Switched to `created()`.

3. **Setup issued a request inconsistent with PRD.** `test_errors.py::test_a_draft_finding_aid_cannot_skip_review_and_publish` built its aid with `arrangement_level="SUBSERIES"`, which PRD §3.5 does not declare — so the PRD-faithful implementation *correctly* answered `ERR_INVALID_REQUEST` per §2.6 rung 3 and the setup never reached the assertion. Changed to `SERIES` (incidental to this test).

4. **Factory called with a duplicated argument.** `test_entities.py::test_record_series_create_without_a_schedule_reference_is_invalid` passed `retention_schedule_id` both positionally and as a `None` kwarg, raising `TypeError` before any HTTP call. Rewritten to build the full valid payload and `del` the one required key, so §2.6 rung 3 is the sole rule that can fire. Verified the implementation validates presence (`vid`) ahead of resolution (`fetch`), so the expected 400 correctly beats the 404.

Suite-wide greps confirmed each bug class was isolated to the failing tests (no other mis-wrapped creates, no other undeclared enum value, no other bare-`Z` equality assertion). Hygiene verified: no stray test dirs under `workspace/`, storage remains in-memory only with nothing seeded at startup.

### Orchestrator verification of the Step 7 claim

The subagent deleted its `results.*.json` on exit, so the orchestrator re-ran the full 8-round sweep itself under `setsid nohup` (09:06:34Z -> 09:16:18Z) and read every per-round file directly:

```
round 1: 133 / 133 failed= 0      round 5: 133 / 133 failed= 0
round 2: 133 / 133 failed= 0      round 6: 133 / 133 failed= 0
round 3: 133 / 133 failed= 0      round 7: 133 / 133 failed= 0
round 4: 133 / 133 failed= 0      round 8: 133 / 133 failed= 0
```

The clean sweep is independently confirmed and `workspace/implementation/results.{1..8}.json` are left in place as the required artifacts. Because Step 7 applied 4 `test_suite/` fixes (0 deletions, 0 `test_helpers/` fixes, 0 `implementation/` fixes), Step 8's skip condition is NOT met and Step 8 will run.

## Step 8: Finalize PRD — 2026-09-04T09:26:00.000Z

`PRD_FINALIZED.md` produced. One edit was warranted; three of the four Step 7 items were pure test-artifact bugs with no underlying PRD silence.

## Line counts
- `PRD.md`: 520 lines
- `PRD_FINALIZED.md`: 522 lines — **+2 lines, +0.38%**
- Diff is a single insertion at §2.4; every other byte is verbatim.

## Changes
- **§2.4 — insert — instant rendering is universal, not just `created_at`: every instant-valued response field is normalised to UTC with exactly three fractional digits, including client-supplied instants echoed back — `implementation/core.py:32-47` (`fmt_instant`), `core.py:189-200` (`serialize`), `validation.py:109-115` (`vinstant` -> `parse_instant`).**

### Pre-edit search log (mandatory §2.4 edit)
- **(a) Subject:** the wire rendering of every instant-valued field, and whether client-supplied instants are echoed verbatim or normalised.
- **(b) Impl paths enumerated:** `core.py:fmt_instant` (single formatter, `%03d` of `microsecond // 1000`, string passthrough branch) and `core.py:serialize` (the only path from a row to JSON, used by every `object_response`/`collection_response`); `core.py:register`/`touch` for `created_at`/`updated_at`; `response.py:_base_meta` for `api_request_timestamp`; `validation.py:vinstant` -> `core.py:parse_instant` (offset-aware, naive-as-UTC, `astimezone(utc)`). Grepped every `parse_instant` / `clock.now()` / instant-field write site: `config.py:131` (`_retention_expiry`, built as a `datetime` at `23:59:59.000`), `config.py:202,215` (`effective_from`), `config.py:256,307` (`activated_at`/`released_at`), `custody.py:365` (`published_at`), `custody.py:195` + `services/lookup.py:124-126` (`last_loan_window_end`, copies a `window_end` datetime), `preservation.py:76,110-125,222` (`satisfied_at`, migration `window_start`/`window_end`), `access.py:397` (`completed_at`), `heritage.py:101,115-124,166,226-244,306,327` (`certified_at`, `interview_date`, `embargo_until`, `consent_signed_at`, loan windows, `recovery_until`, `checked_out_at`, `returned_at`), `deaccession.py:227` (`current_utc`). Result: **no** instant is ever stored as a raw string, so the `fmt_instant` passthrough branch is dead and all 19 instant fields render identically.
- **(c) Wording adjustments:** (i) said "carried to exactly three fractional digits" rather than specifying how excess sub-millisecond digits are handled — `fmt_instant` truncates while §2.10 speaks of millisecond resolution, and pinning that would have made a claim Step 7 never exercised; (ii) added "A field whose value is null is returned as null" because `fmt_instant(None)` short-circuits, so the universal claim would otherwise mis-describe the many nullable stamps (`released_at`, `certified_at`, `embargo_until`, ...); (iii) scoped the echo clause to "every instant the client itself supplied **and the resource carries**", which keeps `POST /_clock/set_current_utc` out of it — `deaccession.py:229` returns `empty_response(200)` and never echoes `current_utc`.

## Items deliberately not patched
- **201 vs 200 (`create_storage_zone`).** §4 already states creation endpoints return 201, and `POST /storage-zones` is unambiguously one. Verified the impl returns 201 on exactly the 17 top-level `POST` create endpoints and 200 everywhere else, including `POST /storage-zones/{id}/environment-readings` (`custody.py:284`, mutates the zone rather than minting a row) and `POST /_clock/set_current_utc`. Pure test-artifact bug — no PRD silence.
- **`arrangement_level="SUBSERIES"`.** §3.5 declares exactly `COLLECTION`/`SERIES`/`FILE`/`ITEM` and §2.6 rung 3 pins undeclared enum members to `ERR_INVALID_REQUEST`; `validation.py:16` matches. Fixture bug.
- **Duplicated `retention_schedule_id` kwarg.** A `TypeError` in the factory, never an HTTP round trip. The 400-beats-404 ordering it exposed is already pinned by §2.6 rungs 3 and 5, and `config.py:104` (`vid`) does run before `config.py:114` (`fetch`). Fixture bug.

## Step 9: Complete PRD — 2026-09-04T09:50:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single subagent. Rationale: the implementation is 3315 lines across 16 files and a single-pass scan of that surface has previously produced a byte-identical output — i.e. the scan silently never ran. Partitioning makes each pass's coverage claim checkable, and the orchestrator verified after each pass that the file had actually grown and that earlier passes' hunks survived.

Final output: `workspace/PRD_COMPLETED.md` — 522 lines / 125,126 chars, vs `PRD_FINALIZED.md` 522 lines / 111,709 chars (**+13,417 chars, 46 changed lines, 0 new lines** — every edit in-paragraph, no new sections). Not byte-identical to its source; ends at a real section boundary (last row of the §5 error table). **55 findings total: 44 ambiguity-pins, 11 mismatch-revisions.**

### Pass A — app.py, core.py, errors.py, middleware.py, response.py, validation.py, routes/config.py

21 changes (18 ambiguity-pins, 3 mismatch-revisions). `errors.py` needed no change (status map matches §5 exactly).

- §2.1 — revise — ambiguity — both identity headers are read whitespace-trimmed; a present-but-blank header counts as absent for `ERR_UNAUTHENTICATED` — `middleware.py:26-34`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `core.py:97,105`
- §2.2 — revise — ambiguity — `api_request_timestamp` renders the logical clock, not wall-clock, so two requests at the same clock instant carry identical timestamps — `response.py:14-18`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1-100, negative `offset` -> `ERR_INVALID_REQUEST` (400), decided after auth rungs — `response.py:44-72`
- §2.3 — insert — ambiguity — `has_more` = `offset` + rows returned < `total_count` — `response.py:84`
- §2.3 — insert — ambiguity — `created_at` ties (common because the clock is logical) break by creation order — `core.py:186`
- §2.3 — insert — ambiguity — filters are exact case-sensitive string equality; non-matching/off-enum values yield an empty page rather than 400; unlisted query params ignored — `response.py:93-101`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read the logical clock — `core.py:152-157,180`
- §2.4 — insert — ambiguity — accepted input forms for client instants (trailing `Z`, numeric offset converted to UTC, naive read as UTC; unparseable -> 400); sub-millisecond precision truncated, not rounded — `core.py:32-81`
- §2.4 — insert — **mismatch** — `version` advances at most once per row per request, not once per field written — `core.py:163-181`, `app.py:37-39`
- §2.6 rung 3 — insert — ambiguity — explicit JSON `null` treated as omitted; type checks incl. bool-is-not-int; identifier fields must be non-empty strings *at this rung, ahead of reference resolution*; body must be a JSON object, absent body read as `{}` — `validation.py:29-48,64-141`
- §2.10 — revise — **mismatch** — instant comparisons happen at the supplied precision (microsecond-capable), which for rendered three-digit values amounts to millisecond resolution — `core.py:50-81`
- §2.10 — insert — ambiguity — cents are JSON integers while the two-decimal appraisal figures are fractional JSON numbers (`88.0`, `75.0`) — `config.py:55,412,430`, `core.py:196-197`
- §3.1 — insert — ambiguity — `min_appraisal_score_for_permanent` with finer precision is rounded half up to 2dp at registration, not rejected; later comparisons read the rounded value — `config.py:55`
- §3.1 — insert — ambiguity — inverted `earliest_record_year`/`latest_record_year` is `ERR_INVALID_REQUEST` at rung 3, ahead of `retention_schedule_id` resolution — `config.py:109-114`
- §3.1 — insert — ambiguity — the dispose `ON_LOAN` guard is checked last of four, `ERR_ITEM_STATE_INVALID` (409); `disposition_certificate_reference` required non-empty, no max length — `config.py:162,176-181`
- §3.2 — insert — ambiguity — creating an appraisal increments the series' `version` even when nothing was superseded (first appraisal -> series v2, invalidating a held `expected_series_version`) — `config.py:378`
- §3.2 — revise — **mismatch** — finalisation does not require `ACTIVE`; it only rejects `SUSPENDED`/hold-active, so `ELIGIBLE_FOR_DISPOSITION`, `PERMANENT` and `DISPOSED` series may still be finalised — `config.py:425` via `398-400`
- §3.2 — insert — ambiguity — a non-`ACTIVE` series keeps its `disposition_state` whatever the recommendation; only `current_appraisal_id` changes, and `version` still increments — `config.py:440-446`
- §3.3 — insert — ambiguity — `release_note` required non-empty, no max length — `config.py:300`
- §3.3 — insert — ambiguity — the "no other `ACTIVE` hold" proviso governs the whole release reconciliation: with another hold active, only the hold row changes — `config.py:309-324`

### Pass B — services/calc.py, services/lookup.py, routes/custody.py, routes/preservation.py

14 changes (9 ambiguity-pins, 5 mismatch-revisions). Pass A's 21 edits verified intact.

- §2.11 — revise — **mismatch** — readings are neither rounded nor range-checked; supplied precision is echoed and coerced to a JSON float (`18` -> `18.0`, `18.25` classified and returned as `18.25`) — `calc.py:244`, `custody.py:231`
- §2.10 — revise — **mismatch** — the flat "carry one decimal place" claim softened and pointed at §2.11 — `validation.py:77`
- §3.4 — revise — ambiguity — `provenance_statement` / `transfer_instrument_reference` required non-empty, no upper bound, stored verbatim — `custody.py:101`
- §3.4 — revise — ambiguity — `rejection_reason` shape; rejection leaves `units_on_loan`/`units_deaccessioned` untouched and recomputes both accession counters on the spot (`processed_unit_count` drops to 0) — `custody.py:144,156,157`
- §3.5 — revise — **mismatch** — both aid counters are NOT refreshed by every cascade: impl recomputes both at submit-review, `described_item_count` alone at publish, and the deaccession cascade *increments* stored `stale_item_count` by 1 rather than recomputing; rejection/execution/disposal refresh neither — `lookup.py:107,113`, `custody.py:346,364`, `deaccession.py:159`
- §3.6 — revise — ambiguity — activation writes the census result to `at_risk_unit_count` — `preservation.py:72`
- §3.6 — revise — ambiguity — job create: `units` unbounded and not compared to the item's `unit_count`; window comparison at rung 3 ahead of both reference resolutions; item `status`/`storage_zone_id` unconstrained, and when item zone != plan zone the capacity rule reads the item's zone while budget/census read the plan's — `preservation.py:109-118`
- §3.6 — revise — ambiguity — `volume_discount_pct` serialised as a fractional JSON number, so a zero discount returns `0.0` — `calc.py:189`
- §3.6 — revise — ambiguity — a non-`ACTIVE` funding plan is refused with `ERR_PLAN_STATE_INVALID`; the four approve conditions decide plan-status -> SoD -> zone capacity -> budget — `preservation.py:162-173`
- §3.6 — revise — ambiguity — start refuses a non-`ACCESSIONED` item with `ERR_ITEM_STATE_INVALID`, ahead of the zone-compliance check — `preservation.py:189`
- §3.6 — revise — **mismatch** — completion hop two censuses the named plan's own `storage_zone_id`, not "the plan covering that item's zone" — `preservation.py:219`
- §3.6 — revise — ambiguity — `cancel_reason` required non-empty, no upper bound, on all three branches — `preservation.py:231`
- §3.7 — revise — **mismatch** — "ties broken by `created_at` alone" was self-contradictory; fee lines sort by `created_at` with ties by creation order per §2.3, and order cannot move the total since each line rounds before summation — `calc.py:135`
- §3.8 — revise — ambiguity — `last_loan_window_end` refresh also runs on check-out, return and cancel (not confirm), ties by creation order, and bumps the item's `version`/`updated_at` only when the recomputed value differs — `lookup.py:123`, `heritage.py:251,312,334,347`

Two behaviours deliberately left unedited after verifying they are unobservable: `recompute_accession_counters`' change-guard (every caller always changes a counter) and completion's unconditional `item["status"] = "ACCESSIONED"` (no other route can leave `IN_TREATMENT`).

### Pass C — routes/access.py, routes/heritage.py, routes/deaccession.py

20 changes (17 ambiguity-pins, 3 mismatch-revisions). All 32 lines A and B had changed verified still changed.

- §3.7 — insert — ambiguity — `suspend_reason` required non-empty, no upper bound — `access.py:79`
- §3.7 — insert — ambiguity — filing is not gated on requester status; a request may be filed against a `SUSPENDED` requester, only screening/decision are blocked — `access.py:100-145`
- §3.7 — insert — ambiguity — a cited `finding_aid_id` need only resolve: no series-membership check, publication unexamined until approval — `access.py:114-115`
- §3.7 — insert — ambiguity — read endpoints are not ownership-scoped; a `Requester` sees all requester/access-request rows matching filters — `access.py:60-72,148-166`
- §3.7 — revise — **mismatch** — the `REVALIDATION_REQUIRED` clearing does not force a fresh screening: pointer and old screening survive, so only `FULL` is gated (null score fails the 75 threshold) while `REDACTED`/deny still decide on the retained screening — `access.py:182-187,266-276`
- §3.7 — insert — ambiguity — omitted `purpose` on revise leaves the stored value unchanged — `access.py:213-214`
- §3.7 — insert — ambiguity — revise resolves item ids *after* ownership, state and non-empty checks (not at rung 5) — `access.py:196-209`
- §3.7 — insert — ambiguity — the five approval gates decide in §2.6 ladder order, not the narrated order — `access.py:242-276`
- §3.7 — insert — ambiguity — `deny_reason` required non-empty, no upper bound — `access.py:291`
- §3.8 — insert — ambiguity — `evidence_item_ids` need only resolve; no series-membership rule — `heritage.py:42-44`
- §3.8 — insert — ambiguity — `continuous_use_coverage_pct` is the JSON integer `0` on a DRAFT package and a fractional number after certification (`25.0`) — `heritage.py:56,92`
- §3.8 — insert — ambiguity — `release_state` is stored, rewritten only by the two axis endpoints, never recomputed on read (matters after a clock rewind) — `heritage.py:181,211`
- §3.8 — insert — ambiguity — loan `units` unbounded / no unit_count comparison at request; item `status` unconstrained at request — `heritage.py:225,232`
- §3.8 — revise — ambiguity — check-out additionally requires an `ACCESSIONED` item (`ERR_ITEM_STATE_INVALID`); order is item-state -> window -> units — `heritage.py:297-304`
- §3.9 — revise — ambiguity — `recipient_repository`: whitespace-only counts as absent, string type-check at rung 3 ahead of item resolution, optional and stored verbatim on `DESTRUCTION`; `units` unbounded; creation examines neither item status nor series — `deaccession.py:24-43`
- §3.9 — insert — ambiguity — `clearance_note` shape, written only when supplied (omission preserves the prior note) on all three endpoints — `deaccession.py:85,96-97,213-214`
- §3.9 — revise — ambiguity — approval also requires an `ACCESSIONED` item (`ERR_ITEM_STATE_INVALID`) checked *after* the live-loan check; "five things" -> "six things" — `deaccession.py:143-147`
- §3.9 — insert — ambiguity — `transfer_reference` required non-empty, no upper bound — `deaccession.py:182`
- §3.9 — revise — **mismatch** — removed the promise that `recipient_repository` is copied onto the item's audit trail; it is written to the private key `_recipient_repository`, which `core.serialize` strips, so no response exposes it (finding handed from pass B, independently CONFIRMED) — `deaccession.py:196` + `core.py:192`
- §3.9 — revise — **mismatch** — rejection leaves the item "in whatever status it occupies", not necessarily `ACCESSIONED` (rejection never inspects item status) — `deaccession.py:205-217`

Endpoint role lists in §4 were cross-checked against every blueprint decorator and matched exactly; the `_clock` endpoint, the screening OCC guard (rung 10), both interview axes, and the certify gate order needed no change.

### Final state

- `workspace/PRD_COMPLETED.md` written (522 lines, 125,126 chars, ends at a real section boundary).
- `workspace/implementation/results.{1..8}.json` present — all 8 rounds `133/133 failed=0` from the orchestrator's own setsid sweep at 09:06:34Z-09:16:18Z.
- No implementation or test file has been modified since that sweep (newest mtime 08:56), so the green result still describes the delivered artifacts. Steps 8 and 9 touched only PRD documents.
- Pipeline complete.

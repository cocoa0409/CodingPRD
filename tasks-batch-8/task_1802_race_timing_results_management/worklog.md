# Worklog — task_1802_race_timing_results_management

## Step 1: Create Task Directory — 2026-08-14T17:30:00.000Z

Pre-created by the invoking pipeline run: `tasks/task_1802_race_timing_results_management/` and `tasks/task_1802_race_timing_results_management/workspace/` already existed; no index scan or directory creation performed by this orchestrator.

## Step 3: Copy Shared Files — 2026-08-14T17:31:33.633Z

Copied `./INSTRUCTION.md` to `tasks/task_1802_race_timing_results_management/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T18:12:11.333Z

All three scaffold artifacts are written, linted clean, and self-audited.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/SCAFFOLD.yaml` — §1.0–§1.7 (response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles). Contains **no** `scaffold_difficulty_design` or `scaffold_corner_design` keys — verified programmatically.
- `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:` (§1.8).
- `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:` (§1.9).

### Counts
- **Entities: 12** — Race, Wave, TimingPoint, Registration, Chip, TimingRead (append-only, `common_fields: false`), Result, ResultFlag, Protest, Correction, Certification, Award
- **Endpoints: 47** (Expert band overshoot is lint-mandated FK reverse-reachability read surface; all logic density lives in gates, not CRUD)
- **Error codes: 30** (all referenced by ≥1 validation row; all triggerable — one untriggerable config-drift error was found and removed during authoring)
- **State machines: 12** — cycles on Race (FINALIZED→AMENDMENT_OPEN→PROVISIONAL_PUBLISHED), Chip, TimingRead, Result, Certification; parallel dimensions on Registration (lifecycle × payment)
- **Difficulty-design instances: 19** (9 rules; combinatorial_formula carries 3 instances covering modes (a) age-bracket categorization, (b) nested-rounding live pace, (c) pinned flag→exclusion→rank evaluation order)
- **Corner-design instances: 60** (52 active with full structured recipes + 8 `excluded_because:` stubs), across all 9 claim-guide sections

### Difficulty posture (per directive)
Expert band targeted and pushed via coupling: dual chip/gun/wave-offset ranking variants with literal-computed divergent outcomes (A wins gun 1925000<1940000, B wins chip 1910000<1920000), a 5-hop correction→read→result→award→certification-revocation cascade, OCC on `Race.version` for publish and correction adjudication (412), two segregation-of-duties pairs (protest filer≠resolver, timing-locker≠certifier), and boundary literals at exact equality (course-cut pace floor ±1ms, protest window strict< vs finalize inclusive>=, qualifying standard inclusive<=).

### Verification
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1155 calls scanned across 71 instances)
- Custom audits passed: grounds resolvability, instance-name uniqueness (79 unique), placeholder closure, forbidden-vocabulary scan, error↔validation cross-reference.
- Every formula-derived assert literal was executed against the pinned formulas in Python — this caught and fixed one real arithmetic slip (gun time 1866000, not 1865000, for a 07:00:06-start/07:31:06-finish runner) before delivery.
- Logical clock endpoint declared with the mandatory `2026-08-01T00:00:00Z` startup default; every state in every machine is reachable from empty-DB via declared endpoints (test-driving endpoint needed only for the clock).

No sibling task directories were inspected at any point.

## Step 4: Generate PRD — 2026-08-14T18:23:08.775Z

PRD generation complete. All three hard contracts verified mechanically and by manual rule-coverage review.

### Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/workspace/PRD.md`
**Line count:** 292 lines

**Section list:**
- §1. Introduction (2 paragraphs — business context + event-sourcing design premise, `/race-timing` mount)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (6 roles, all `identity: opaque` rendered individually; `X-User-ID`/`X-User-Role`; auth error IDs)
  - 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, including `req_RANDOMALPHANUM123456` and empty `"data": { }`)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, four `meta` fields)
  - 2.4 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, staff-only)
  - 2.5 Common Resource Properties and the Append-Only Read Log (`id`/`created_at`/`updated_at`/`version`; TimingRead exception explicit)
  - 2.6 Time Units, Precision, and Rounding
  - 2.7 Request Validation Pipeline (10-stage fixed ordering)
  - 2.8 Optimistic Concurrency Control on the Race
  - 2.9 Segregation of Duties
  - 2.10 Referenced Resource Existence and Resolution Order
  - 2.11 Derived Standings and Immediate Consistency
- §3. Business Logic & Workflows — 9 subsections: 3.1 Race Setup (waves, timing points), 3.2 Registration Intake (age/bracket computation, payment, withdrawal), 3.3 Chip Fleet & Check-In, 3.4 Timing Lock & Race Start, 3.5 Read Ingest & Course-Cut Surveillance, 3.6 Publishing Results (4-phase recompute, dual rankings, awards), 3.7 Flags/Protests/Corrections (amendment loop, cascades C1/C2), 3.8 Finalization & Certification, 3.9 Live Results Feed
- §4. Endpoint Definitions (4-column table, 47/47 rows, all paths and statuses cross-checked)
- §5. Error Code Catalogue (2-column table, 30/30 rows — the scaffold's own "29 codes" header comment undercounts; the `errors[]` array contains 30 entries and all 30 are tabulated with verified HTTP statuses)

**Quality checklist results:**

```
Contract 1 — Field-Name Coverage:
- entities[].fields: 73 required, 73 present, 0 missing
- endpoints[].request_body: 42 required, 42 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- endpoints[].path_params: 11 required, 11 present, 0 missing (all also standalone tokens)
Status: PASS

Contract 2 — Rule Coverage (manual walk of all six categories + tail):
- validations[] with priority: 32 checked, 32 expressed (global pipeline in §2.7 + per-endpoint
  relative orderings in §3, e.g. overlap→window-shape→freeze for timing-point creation;
  state→OCC→cutoff for publish; state→window→protests→flags for finalize)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_race_version +
  ERR_STALE_RACE_VERSION/412 named; stale-view framing only, no time-overlap language)
- state_machines[].transitions: 38 checked, 38 fully expressed
- calculations[]: 8 checked, 8 fully expressed (incl. pinned nested rounding in live board,
  inclusive qualified/cutoff boundaries, strict-less-than pace floor at 2 min/km in ms,
  earliest-CONFIRMED-flag exclusion_reason, gap-free 1..K ranks, 30-minute protest window)
- validations[] conditions: 32 checked, 32 matchable to error_id in prose (30/30 error IDs
  appear in §2/§3)
- endpoints[].side_effects / applies_to: all expressed (C1/C2 cascades step-for-step;
  multi-endpoint scopes enumerated, e.g. intake gate on register/pay/confirm, freeze on
  create/deploy/delete, kind-mismatch checked at both filing and adjudication)
- entities[].fields[] structured content: defaults/nullability/initial states all placed
- sibling-branch symmetry: RETURNED-vs-LOST, UPHELD-vs-DISMISSED, APPROVED-vs-REJECTED,
  CONFIRMED-vs-DISMISSED, gun-vs-chip variants all at equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned: 486
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checklist items: no fuzzy/approximating words, no pseudocode operators in §3 prose, all 63 enum/state literals present verbatim (including `AG_F_30_34`, `1-19`, `80+`, `CORRECTION_APPROVED`), endpoints not covered by OCC explicitly stated to take no version field, constants embedded as business context (2 min/km, 5-year brackets, depth-3 awards, 30-minute window). The withheld difficulty/corner design files were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T18:50:51.350Z

All staging checks pass. Generation is complete. Final summary:

### Files written

**`test_helpers/`** (9 files, at `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/test_helpers/`):
- `types.py` — 12 entity TypedDicts (TimingRead correctly carries only `id`+`created_at`), 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (47 methods, all under `/race-timing`)
- `api_errors.py` — all 30 catalogue codes + HTTP map registered with `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `parse_iso` (semantic timestamp comparison), `assert_award_singleton_per_category_place`
- `factories.py`, `constants.py` (only PRD-derivable constants: 120 s/km pace, 30-min window, depth-3 awards, 5-year brackets — **no** `WAVE_GAP_MINUTES`, which the PRD never prices), `test_users.py` (6 opaque roles + per-instance builders for SoD id threading), `fixtures.py` (race-construction engine `build_race`/`start_waves`/`ingest_reads`/`publish_race`/`finalize_race`/`certify_race` plus named composites `setup_single_finisher_published_race`, `setup_divergence_race`)
- `__init__.py` barrel export

**`test_suite/`** (12 files, at `.../test_suite/`): `conftest.py` + 11 test files (`test_01` race creation/envelope … `test_11` auth/RBAC).

### Test counts
- **Queue A (Difficulty): 17/19 instances covered, 35 tests** (each ≥2, tagged `Design: Difficulty/<rule_id>/<instance.name>`)
- **Queue B (Corner): 50/52 non-stub instances covered, 51 tests** (tagged `Design: Corner/<section>/<instance.name>`)
- **86 tests total**; all 8 `excluded_because:` stubs' cross-references verified resolving to real difficulty instances.

### Skipped instances (4) and reasons
1. `Difficulty/resource_temporal_overlap/wave_start_min_gap_buffer` — asserts +10min accepted / +9min rejected, but the PRD names `WAVE_GAP_MINUTES` only symbolically and never states the value 10; not uniquely derivable.
2. `Difficulty/priority_pair_validation_conflict/wave_create_spacing_beats_index_taken` — same root cause: the +5min scenario's winner error depends on the unpriced gap constant.
3. `Corner/entities/wave_index_unique_returns_409` — same root cause: whether a +30min wave reaches the uniqueness check depends on the unpriced constant.
4. `Corner/validations/assign_chip_twice_returns_409` — the instance asserts `ERR_CHIP_ALREADY_ASSIGNED` for a CHECKED_IN registration taking a second chip, but PRD §3.3 verbatim says the binding is "evaluated state-first" and "a registration in any other lifecycle state … fails the state check with `ERR_INVALID_STATE`"; the asserted outcome contradicts the PRD-derived one.

### One PRD-first deviation inside a covered instance
- `correction_cascade_to_certification_revocation`: the instance's hop-2b says A's result "stays OFFICIAL", but A's `age_group_rank_chip` changes 2→1, and PRD §3.7 verbatim moves "any `OFFICIAL` result whose computed fields change" to `AMENDED`. The test asserts A is `AMENDED` revision 2 (PRD wins over the instance literal).

### Staging check results
- `py_compile` clean; `pytest --collect-only` collects 86 tests; pyflakes clean.
- Tag audit: 86/86 tests carry exactly one Design line; zero untagged, zero dual-tagged, zero tags pointing to non-existent instances.
- Citation audit: all 130 quoted docstring spans (≥6 words) survive whitespace-normalized literal match against PRD.md; zero failures.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings.
- Residual documented risks (kept per design literals, noted not weakened): live-board entry field names (`registration_id`, `projected_total_sec`) are implied rather than enumerated by PRD §3.9; the fingerprint assertion uses the instance's exact string `'1:START:0.0,2:FINISH:5.0'` (float-format sensitivity).

## Step 6: Generate Implementation — 2026-08-14T18:50:51.350Z

All verification is complete. No stray server processes from this task remain (the pgrep hits belong to other concurrent task directories and were left untouched).

### Summary

**Task**: Generate the complete Python + Flask implementation for `task_1802_race_timing_results_management` from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md only (difficulty/corner/test files were not read).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/workspace/implementation/`):
- `start.sh` (executable, guarded pip install, `exec python3 app.py`), `requirements.txt`
- `app.py` (entry point, envelope-aware error handlers for ApiError/400/404/405/500)
- `clock.py` (logical clock), `db.py` (in-memory stores + lock + `new_entity`/`touch`), `errors.py` (all 29 error IDs), `response.py` (envelope), `middleware.py` (auth/role guard), `serializers.py`, `util.py` (ISO8601 parse/format, exact-ms math, round-half-up), `validators.py` (body/field/existence/pagination helpers)
- `routes/`: `clock_routes.py`, `races.py`, `waves.py`, `timing_points.py`, `registrations.py`, `chips.py`, `timing_reads.py`, `results.py`, `result_flags.py`, `protests.py`, `corrections.py`
- `services/recompute.py` (time derivation, 4-phase ranking with exclusions, award waterfall with swap rule, course-cut pace check + missing-split sweep, DNF sweep, correction cascade C1, flag cascade C2, live-board projection with pinned nested rounding)

**Endpoint count**: 47 endpoints implemented — every row of the §4 routing table (clock setter, race lifecycle incl. publish/finalize/certify/live-board/sub-lists, waves, timing points, registrations, chips, timing reads, results, result flags, protests, corrections, per-registration awards).

**Logical clock**: module-level in `clock.py`; boots to exactly `2026-08-01T00:00:00Z` on every fresh process and never touches wall-clock time. `POST /race-timing/_clock/set_current_utc` (staff roles only) sets it. All stamps (`created_at`/`updated_at`, lock/start/publish/finalize/issue stamps, `api_request_timestamp`) read from it; window/cutoff comparisons (protest window strict `<`, finalize inclusive `>=`, publish cutoff inclusive `>=`) use second-precision truncation; chip `read_timestamp` keeps millisecond precision. Since all state lives in process-local dicts, each `start.sh` re-invocation boots completely empty — verified live: after reboot the clock reads the default and `GET /results` returns `total_count: 0`.

**Boot contract confirmed**: `bash start.sh` runs the server in the foreground via `exec`, bound to `0.0.0.0` on `$PORT` (verified with `ss` showing `0.0.0.0:18101`), HTTP-responsive within seconds; the dependency install is guarded by `python3 -c "import flask"` so per-test reboots skip pip.

**Validation performed**: three smoke suites (111 assertions, all passing) covering the full workflow — setup → lock → check-in → wave start → read ingest (SCORED/REJECTED/duplicate) → publish with ranks/awards/qualified → protest window + SoD + uphold cascade → amendment loop → finalize → certify → correction cascade with AMENDED/revision bump and certification revocation, plus edge cases (deassign RETURNED/LOST, re-check-in, kind-mismatch, pagination meta, 401/403/404 envelopes).

**One judgment call to flag**: `WAVE_GAP_MINUTES` is referenced by both PRD and scaffold but never assigned a numeric value anywhere in the repo. Implemented as **5 minutes** (documented in `routes/waves.py`) — catches identical/adjacent start-time violations while not rejecting generously spaced waves.

## Step 7: Run Tests and Iterate — 2026-08-14T19:09:29.858Z

All 8 parallel rounds pass 86/86 with zero failures in the union. The loop is complete.

### Summary

**Iterations run**: 2 (sweep 1: 82/86 in all 8 rounds, union of 4 deterministic failures; fixes applied; sweep 2: 86/86 in all 8 rounds, union failing = 0).

**Tests deleted**: none. No test required deletion; the 4 failures resolved as 2 unique-derivability relaxations (STEP 1c partial-coverage handling — covered assertions kept, uncovered ones removed) and 1 test-setup bug (STEP 2), with 1 test sharing both patterns.

**Fixes applied to `test_helpers/`**: none — the fixtures/factories/header builders were all PRD-consistent.

**Fixes applied to `test_suite/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/test_suite/test_03_timing_points_and_locking.py` — `test_lock_after_deploy_captures_fingerprint_and_locker`: replaced the exact-string fingerprint assertion (`"1:START:0.0,2:FINISH:5.0"`) with a structural check (two comma-joined `index:kind:distance` segments in point_index order, float-parsed distances). PRD §3.4 pins segment structure but never the distance's decimal rendering — a faithful reader could produce `"1:START:0,2:FINISH:5"`, so the exact string failed unique derivability (this was the generation-time flagged residual risk).
- Same file — `test_timing_point_mutation_after_lock_rejected`: setup created SPLIT at point_index 3 / 2.5 km after FINISH at index 2 / 5.0 km, violating PRD §3.1's "point_index … must strictly increase with distance_km", so the PRD-faithful implementation correctly 400'd the setup. Renumbered to START 1 / SPLIT 2 / FINISH 3, and the post-lock create now reuses the freed index 2 so only the configuration freeze can reject it.
- `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/test_suite/test_09_protests_corrections_amendment.py` — `test_full_amendment_loop_recloses_and_keeps_unchanged_award`: removed `basis_time_ms == 1865000` on the unchanged-winner award. PRD §3.6 says "an award whose winner is unchanged is kept exactly as it is" — whether `basis_time_ms` refreshes to the corrected winning time is not uniquely determined (kept-as-is vs projection-refresh); winner identity, cardinality, CONFIRMED status, and no-REVOKED assertions retained.
- Same file — `test_singleton_cardinality_and_confirmed_sets_after_cycle`: removed `basis_time_ms == 2060000` on B's unchanged-winner OVERALL_M place-2 row (same pattern). Kept the swap-created AG rows' time assertions (replacement rows record the current winning time — derivable) and place-1's 1925000 (A's gun time untouched by the correction, so both readings agree).

**Fixes applied to `implementation/`**: none — the implementation was PRD-faithful in all 4 cases (compact fingerprint rendering, §3.1 monotonicity rejection, and "kept exactly as it is" award semantics, the latter matching the scaffold's "kept unchanged" rule).

## Step 8: Finalize PRD — 2026-08-14T19:12:45.117Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/workspace/PRD_FINALIZED.md` with exactly two inline revisions, both traced to `<step_7_diff>` items.

### Summary

**Line counts / delta**: PRD.md 292 lines, 50,236 bytes → PRD_FINALIZED.md 292 lines, 50,797 bytes. Line delta 0% (edits are inline within existing paragraphs); byte delta +561 (+1.12%).

**Changes**
- §3.4 — revise — appended a sentence to the `timing_config_fingerprint` spec pinning the distance rendering: whole-number distances render with no fractional part (`0`, `5`), fractional distances in plain decimal notation (`2.5`), with the worked example `1:START:0,2:FINISH:5` — `implementation/util.py:61-67` (`fmt_km`), `implementation/routes/races.py:174-178`.
- §3.6 — revise — extended "an award whose winner is unchanged is kept exactly as it is" to pin that no field of the existing row is rewritten: `basis_time_ms` retains the value recorded at row creation rather than refreshing to the winner's current recomputed time; only a replacement row records the current winning time — `implementation/services/recompute.py:283-306`.
- The third step-7 item (§3.1 `point_index`/`distance_km` monotonicity) was a pure test-setup bug: PRD §3.1 already pins "point_index … must strictly increase with distance_km" and the impl enforces it (`implementation/routes/timing_points.py:95-109`). No PRD edit.

**Per-edit pre-edit search log**

Edit 1 (fingerprint rendering):
- (a) Subject: string rendering of `distance_km` inside `timing_config_fingerprint`.
- (b) Enumerated via grep for `fingerprint`/`fmt_km` across `implementation/`: sole post-creation writer `routes/races.py:174-182` (lock-timing); init `None` at `routes/races.py:79`; read-back passthrough `serializers.py:28`; helper `util.py:61-67` used only at `races.py:176`. Also verified `distance_km` storage (`validators.py:47-51` `v_num` keeps the JSON int/float as sent; `timing_points.py:50,117` stores it raw) and that no other path string-renders distances (`ser_timing_point`/`ser_race` emit raw JSON numbers; live board emits floats).
- (c) Adjustment: scoped the clause to "within a segment" of the fingerprint so it cannot be read as governing API numeric fields, and described fractional output as "plain decimal notation (`2.5`)" rather than pinning exact float-repr semantics for all values — looser but fully consistent with every enumerated path.

Edit 2 (unchanged-winner award):
- (a) Subject: award-row mutation semantics when a recompute leaves the winner unchanged — whether `basis_time_ms`/`status` refresh.
- (b) Enumerated: `_recompute_awards` (`services/recompute.py:253-306`) is the sole award creator/revoker — kept rows only enter `satisfied` at line 287 with no field writes and no `touch`; all three recompute triggers verified to share the rule — publish (`recompute.py:368` via `races.py` publish-results), correction cascade (`routes/protests.py:163` and `routes/corrections.py:161` → `apply_correction_cascade` → `recompute.py:434`), flag confirmation (`routes/result_flags.py:88`); finalization (`races.py:259-260`) only flips `PROJECTED`→`CONFIRMED`; award list/read endpoints are read-only.
- (c) Adjustment: worded as "no field of the existing row is rewritten" instead of naming only `basis_time_ms`, so the sentence also stays accurate for status retention (a kept `CONFIRMED` row survives the amendment loop untouched), and remains consistent with §3.7's "replacements created `PROJECTED` … `CONFIRMED` status restored only after a subsequent finalization", which speaks only of replacement rows.

## Step 9: Complete PRD — 2026-08-14T19:22:06.691Z

PRD_COMPLETED.md is complete. Final verification confirms 15 changed paragraphs, all in-place (line count unchanged).

### Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1802_race_timing_results_management/workspace/PRD_COMPLETED.md`

**Source vs output:** `PRD_FINALIZED.md` (292 lines / 50,797 chars) → `PRD_COMPLETED.md` (292 lines / 54,136 chars). Char-delta **+3,339**; line count unchanged — all changes are in-paragraph inserts/revisions, no new sections.

**Counts:** 13 ambiguity-pins, 2 mismatch-revisions (15 changes total).

**Walk coverage:** every route file (`races`, `waves`, `timing_points`, `registrations`, `chips`, `timing_reads`, `results`, `result_flags`, `protests`, `corrections`, `clock_routes`), the recompute engine, middleware, validators, serializers, response/clock/db/util layers, cross-checked against §4 routing/roles table and §5 error catalogue (all endpoints, roles, filters, and error IDs matched; stored test runs confirm 86/86 passing, so implementation was treated as stable).

**Changes:**

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected), non-integer values fail `ERR_INVALID_REQUEST`, and any `created_at` ordering/selection ties break by creation sequence — implementation/validators.py:86-107
- §2.5 — insert — ambiguity — `version` counter starts at 1 at resource creation — implementation/db.py:37
- §2.7 — insert — ambiguity — pipeline detail: path identifiers resolve first, then body well-formedness (malformed/non-object/missing-required → `ERR_INVALID_REQUEST`), then body-identifier existence, then field-shape validation; unnamed state/lifecycle failures default to `ERR_INVALID_STATE` — implementation/validators.py:12-76 plus all route handlers
- §2.8 — revise — ambiguity — `expected_race_version` must equal the race's current `version` exactly (any mismatch → `ERR_STALE_RACE_VERSION`, not only stale reads) — implementation/routes/races.py:201, implementation/routes/corrections.py:138
- §3.1 — insert — ambiguity — `WAVE_GAP_MINUTES` pinned to five minutes — implementation/routes/waves.py:22
- §3.1 — insert — ambiguity — device deployment windows are compared fleet-wide across all races, not per race — implementation/routes/timing_points.py:59-67
- §3.3 — revise — mismatch — assign-chip state condition admits an already-`CHECKED_IN` registration holding no chip (the `RETURNED` re-check-in path); success keeps such a registration `CHECKED_IN` — implementation/routes/registrations.py:196-216
- §3.5 — insert — ambiguity — course-cut pace check measures elapsed from the latest `SCORED` start read strictly earlier than the ingested read — implementation/services/recompute.py:344-352
- §3.6 — revise — mismatch — first-publication Result rows are created carrying that publication's computed times/ranks/`qualified` (not "qualified starting false"), and a registration already excluded at creation starts `EXCLUDED` with `exclusion_reason` set and ranks null — implementation/services/recompute.py:184-203
- §3.7 — insert — ambiguity — protest-spawned auto-`APPROVED` correction also carries the protest's `reason` and records the resolving official as `adjudicated_by_user_id` — implementation/routes/protests.py:149-161
- §3.7 — insert — ambiguity — flag cascade also moves any other `OFFICIAL` result whose computed fields change to `AMENDED` with `revision` +1 (same as correction cascade) — implementation/routes/result_flags.py:87-88, implementation/services/recompute.py:217-248
- §3.7 — insert — ambiguity — correction approved while the race is already `AMENDMENT_OPEN` keeps it `AMENDMENT_OPEN` and still increments `amendment_count` — implementation/services/recompute.py:436-437
- §3.9 — insert — ambiguity — board entry shape pinned: registration identity fields, `board_status` (`PROJECTED`/`FINISHED`/`AWAITING_START`), `position` 1..N, named projection and finish fields null where inapplicable; excluded registrations omitted from the board entirely — implementation/services/recompute.py:453-510
- §3.9 — insert — ambiguity — zero-segment projection (start read only): projected pace and remaining time null, projected total equals elapsed seconds — implementation/services/recompute.py:550-561
- §3.9 — revise — ambiguity — the three groups live in the single `entries` array ordered `PROJECTED` → `FINISHED` (`chip_time_ms` ascending, null chip time last, ties by registration creation) → `AWAITING_START` (registration creation), `position` spans the concatenation, and the `bib_number` filter applies after positions are assigned — implementation/services/recompute.py:576-599

**Deliberately skipped (judged framework plumbing, not PRD-interpretable behavior):** Flask-level 404/405/500 handlers (including `ERR_INTERNAL`, which never appears in narrative-guarded flows), whitespace-only auth headers, integral-float leniency in integer fields, and naive-datetime-assumes-UTC parsing.

## Pipeline complete — 2026-08-14T19:22:06.691Z

All 9 steps finished. Final 8-round stability sweep: 86/86 tests passing in every round (results.1–8.json). `workspace/PRD_COMPLETED.md` exists.

## Step 7: Test-Implementation Iteration — 2026-08-14

### Iteration 1
- Sweep 1 (8 parallel rounds, per-test-server isolation): 82/86 passed in every round; union of 4 deterministic failures.
- Fixes (all in `test_suite/`, none in `implementation/` or `test_helpers/`):
  1. `test_03::test_lock_after_deploy_captures_fingerprint_and_locker` — relaxed the exact fingerprint string `"1:START:0.0,2:FINISH:5.0"` to a structural check (two comma-joined `index:kind:distance` segments, ordered, float-parsed distances). PRD §3.4 pins segment structure but not the distance's decimal rendering ("0.0" vs "0"): unique-derivability collapse (DEFAULT/computed-format silence). Documented residual risk from generation confirmed.
  2. `test_03::test_timing_point_mutation_after_lock_rejected` — setup created SPLIT at point_index 3 / 2.5 km after FINISH at index 2 / 5.0 km, violating PRD §3.1 "point_index … must strictly increase with distance_km"; a PRD-faithful implementation must 400 it. Renumbered to START 1 / SPLIT 2 / FINISH 3; post-lock create now uses the freed index 2 so only the freeze can reject. Test bug (fixture-constructed precondition violates PRD).
  3. `test_09::test_full_amendment_loop_recloses_and_keeps_unchanged_award` — removed `basis_time_ms == 1865000` on the unchanged-winner OVERALL_M place-1 award. PRD §3.6: "an award whose winner is unchanged is kept exactly as it is" — refresh vs keep is not uniquely derivable (two-reader divergence). Winner identity, cardinality, CONFIRMED status, and no-REVOKED assertions kept.
  4. `test_09::test_singleton_cardinality_and_confirmed_sets_after_cycle` — removed `basis_time_ms == 2060000` on B's unchanged-winner OVERALL_M place-2 row (same pattern). Swap-created AG rows' time assertions kept (new rows record the current winning time — derivable), as is OVERALL place-1's 1925000 (A's gun time untouched by the correction — both readings agree).
- Sweep 2 (8 parallel rounds): 86/86 passed in all 8 rounds; union failing = 0. CLEAN.

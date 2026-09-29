# Worklog — task_2577_product_content_syndication_digital_shelf_management

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2577_product_content_syndication_digital_shelf_management` and `.../workspace` (pre-assigned path; no index scan performed per orchestrator instruction).

## Step 2: Generate Scaffold — 2026-09-03T17:00:00.000Z

Scaffold generation for task 2577 is complete.

Files:
| Path | Lines |
|---|---|
| SCAFFOLD.yaml | 2621 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 2437 |
| SCAFFOLD_CORNER_DESIGN.yaml | 7828 |

Counts:
- SCAFFOLD.yaml (§1.0–§1.7): 14 entities, 8 state machines, 3 concurrency rules (OCC only), 9 calculations, 46 ordered validations, 52 endpoints, 45 errors, 7 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- Complexity profile: `expert_plus`; archetypes `workflow_orchestration` / `compliance_audit`; layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval`; topology `graph`; state-machine shape `cyclic` (RetailerListing is `parallel_dimensions`); role model `segregation_of_duties`; consistency `immediate`.
- §1.8: 18 difficulty instances (one top-level key).
- §1.9: 107 instances — 80 real recipes + 27 `excluded_because` stubs (one top-level key), in guide section order: entities 18/0, state_machines 21/6, calculations 9/4, validations 11/5, endpoints 6/0, errors 7/6, rbac 4/0, cross_cutting_complexity_layers 3/6, consistency_model 1/0.

Lint verdict (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  2014

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Coverage-audit notes:
- Every `claim_type` is a verbatim row from `references/claim-extraction-guide.md`; no invented names. Guide's "Violation → Error" row is carried by the 13 `error_triggerable` instances in the `errors` section, so all 45 §1.6 error ids appear in assert lines across the two design files.
- All 27 stubs cite a `difficulty_instance` that exists by name in SCAFFOLD_DIFFICULTY_DESIGN.yaml (verified programmatically against its 18 names); no stub carries a `test_recipe`. Zero duplicate instance names.
- Both mandated replay checks were run and surfaced three defects, all fixed: (1) a `computed_read` recipe whose `setup:` prose described a different fixture's slot_count/window than its own chain queued; (2) seven instances whose chains extended past the base fixture but whose prose still asserted the fixture's `feed_slots_reserved == 0, Retailer.version == 1` — one end-state line added to each; (3) an OCC recipe that asserted `syndication_state == PENDING (back from LIVE)`, a transition §1.2 declares only for a requeue of a `PARTIALLY_ACCEPTED` job — replaced with a `cancel` call (TRANSMITTED → CANCELLED, listing PENDING → NOT_SYNDICATED) and its asserts rewritten.
- Every intentionally-failing call captures `$.data.error_id` (lint-negative), and every OCC write is preceded by a fresh `GET` so all `expected_*_version` values interpolate `${...}`.
- Zero hits for the forbidden concurrency vocabulary across all three files.
- The hard constraint was respected: no sibling `tasks/task_*/` directory was listed, globbed, grepped, or read.

## Step 3: Copy Shared Files — 2026-09-03T17:00:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:15:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md`

**Final line count: 466 lines.** The file ends at a real section boundary — the last row of the complete §5 Error Code Catalogue table (`| ERR_ATTRIBUTE_KEY_UNKNOWN | 422 |`), not mid-sentence. No audit footer or contract-report block was written into the file.

**Constraints honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read; the file was built with 9 chunked `cat >>` heredoc appends (no giant single Write).

**Structure:** §1 Introduction; §2 with 10 subsections (2.1 RBAC, 2.2 verbatim response structure, 2.3 Pagination, 2.4 Identity/Timestamps/Logical Clock, 2.5 Flat Collections & Left-to-Right Reference Resolution, 2.6 OCC, 2.7 Score Precision & Rounding, 2.8 Request Evaluation Order with all 46 validations as an explicit priority-ordered list, 2.9 Conserved Quantities, 2.10 Cascade Discipline); §3 with 9 workflow subsections; §4 endpoint table with 52 rows; §5 error catalogue with 45 rows.

**Hard Contract reports:**

Contract 1 — Field-Name Coverage: PASS
- `entities[].fields`: 97 required, 97 present, 0 missing
- `endpoints[].request_body`: 71 required, 71 present, 0 missing
- `endpoints[].query_params`/`outputs`: 19 required, 19 present, 0 missing
- state values missing: 0; enum values missing: 0; roles missing: 0

Contract 2 — Rule Coverage: PASS
- 46 validations rendered in priority order with error IDs and full `applies_to` scopes
- 3 concurrency rules documented with write endpoint, OCC field, `ERR_STALE_VERSION`, 412
- All 8 state machines' transitions covered, including both four-hop cascades and the fork/join with self-loop
- All 9 calculations specified with rounding discipline (two-stage for `shelf_health_index`, round-once elsewhere, five-step pinned-order fee)
- All endpoint `side_effects` covered; sibling-branch symmetry verified (media approve/reject, deployment create branches, deployment approve/reject, withdraw from both states, join vs reject, FIX vs WAIVE, three retailer-response outcomes, requeue from both source states, cancel from both source states)
- 3 specification gaps found during the manual walk and patched: unparseable ISO-8601 window bound → `ERR_WINDOW_INVALID`; `slot_count < 1` and negative decimals → `ERR_INVALID_REQUEST`; `conversion_lift_pct` explicitly allowed to be negative

Contract 3 — §3 Path Purity: PASS
- backtick tokens scanned in §3: 878; tokens starting with `/`: 0; bare HTTP method tokens: 0; method+path combined tokens: 0

Other structural checks: 45/45 errors in catalogue with 0 status mismatches; 52/52 endpoints in §4 with 0 missing paths; 0 error IDs unmentioned in §2/§3; §2.2 present byte-verbatim; 0 operator-syntax backtick tokens; 0 fuzzy-word hits.

Four scaffold ambiguities resolved explicitly in the prose: `requirement_weight_total` defined as the shared denominator including the image weight of 20; `missing_required_keys`/`over_limit_keys` computed against the certified source revision, sorted ascending by key, with the empty-pin case defined; `RejectionError.resolution_note`/`resolved_at` documented as recorded on the row despite absence from the entity table; and for `ERR_ATTRIBUTE_LENGTH_EXCEEDED` the `validations` table was followed over the contradicting `errors[]` condition text (global taxonomy `max_chars` is the write-time hard limit; a retailer's `max_chars_override` only withholds certified credit), with that distinction stated outright.

**Orchestrator truncation check:** `tail -25` confirms the file terminates on the final complete table row of §5; `grep -n '^#'` shows §1–§5 all present with §5 last. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T17:45:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first and is recorded first. Orchestrator note: the two Agent calls went out in back-to-back messages rather than one message, so Step 6's start was ~90s after Step 5's. Step 6's prompt carried an explicit hard prohibition on reading `test_helpers/`, `test_suite/`, and both design YAMLs, and its summary confirms none were read — isolation preserved by contract in addition to timing.)

Implementation complete for task 2577.

## Files (`workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 8 |
| `requirements.txt` | 1 |
| `app.py` | 59 |
| `store.py` | 122 |
| `errors.py` | 81 |
| `envelope.py` | 119 |
| `auth.py` | 50 |
| `validate.py` | 176 |
| `calc.py` | 461 |
| `recompute.py` | 203 |
| `entities.py` | 180 |
| `routes/__init__.py` | 0 |
| `routes/config.py` | 193 |
| `routes/products.py` | 206 |
| `routes/media.py` | 85 |
| `routes/listings.py` | 192 |
| `routes/governance.py` | 210 |
| `routes/syndication.py` | 364 |
| `routes/deployments.py` | 162 |
| `routes/alerts.py` | 71 |
| **total** | **2943** |

## Endpoints
**52 of 52** registered (`app.url_map` reports 52 non-static rules): config 9, products 9, media 4, listings 7, governance 5, syndication 9, deployments 5, alerts 4 — all under `/digital-shelf`, matching the scaffold endpoint table (paths, methods, roles, status codes, filter params).

## Boot confirmation
`PORT=17578 bash start.sh` booted in under 5 s and answered `GET /digital-shelf/retailers` with HTTP 200 and `total_count: 0` (proving the store is empty on a fresh boot — no seeding anywhere). Both smoke servers were killed **by PID resolved from the listening port** (`ss -ltnp | grep ':<port>'` → `kill <pid>`); no pattern-kill was used, and `pgrep -af "task_2577.*app.py"` shows no leftovers.

## Behaviour verified end-to-end against the running server
- Envelope/meta/pagination, `ERR_INVALID_PAGINATION`, 401 vs 403, per-endpoint role matrix, logical clock repositioning (all `*_at` stamps came back as `2026-08-10T00:00:00.000Z`).
- Completeness dual variant: declared 100.00 with `missing_required_keys: ["title"]` on the certified side pre-pin; certified 100.00 after the CR approval join pinned the revision.
- Readiness: 24.00 (accuracy floored to 60 under `OOS_WATCH`) → 84.00 after pin → 89.00 with a LIVE deployment bonus → back to 84.00 after withdraw → 79.00 under a single BLOCKING error (5-point tier).
- Fee ladder: 4 slots → 10000 subtotal → 5 % tier → 9500 cents, non-rush; requeue at 2 slots re-froze the fee at 4750.
- Conserved ledgers: `feed_slots_reserved` 0 → 4 → 2 → 0 across queue/requeue/cancel with a retailer `version` bump per job state write; `ContentVersion.pin_count` 3 = 1 listing pin + 2 active deployments.
- Cascades: retailer REJECTED response → `ERROR_HOLD` + blocking recount; `FIX` resolve → `NOT_SYNDICATED` + readiness with no penalty; observation ingest raised `OUT_OF_STOCK` + `CONTENT_DRIFT` with product `open_alert_count`/`governance_flag` rollup (2 → 1 on resolve, product version bumped).
- Deployments: half-open windows — `[08-11, 08-12)` vs `[08-11T12, 08-13)` → `ERR_DEPLOYMENT_WINDOW_OVERLAP`, while a touching `[08-12, 08-13)` was accepted; error precedence confirmed (asset 404 before CR 404).
- OCC (`ERR_STALE_VERSION` 412), `ERR_WAIVE_NOT_PERMITTED` for a SyndicationOperator waiving BLOCKING, `ERR_BLOCKING_ERRORS_UNRESOLVED` on requeue, `ERR_ALERT_ALREADY_RESOLVED`, `ERR_REJECTION_ERROR_ALREADY_CLOSED`, `ERR_DEPLOYMENT_NOT_ACTIVE`.
- Shelf health two-stage rounding: subscore 67.50 (0.45·80 + 0.25·90 + 0.20·0 + 0.10·90) → index 67.50.

Two documented judgement calls: the `MediaAsset` "state == PENDING" precondition has no scaffold error id, so `ERR_MEDIA_ASSET_NOT_PENDING` (409) was invented; and the rush test is `(window_start − current_utc) < 24h`, so a past window counts as rush. Hard constraints were respected throughout — no `test_helpers/`, `test_suite/`, difficulty/corner design files, or sibling task dirs were read; storage is in-memory dicts only.

## Step 5: Generate Unit Tests — 2026-09-03T18:20:00.000Z

Generation complete for task 2577. Everything lives at the task root; nothing was written inside `workspace/`, and neither `workspace/implementation/` nor any sibling task was read.

## Files and line counts

`test_helpers/` (2325 lines)
- `__init__.py` 24, `api_client.py` 242, `api_errors.py` 104, `assertions.py` 250, `constants.py` 73, `factories.py` 237, `fixtures.py` 953, `test_users.py` 62, `types.py` 440

`test_suite/` (8439 lines, 244 tests)
- `conftest.py` 71
- `test_01_completeness_and_conversion_variants.py` 129 / 5
- `test_02_service_fee_composition.py` 134 / 5
- `test_03_change_request_and_job_cycles.py` 277 / 7
- `test_04_observation_and_join_cascades.py` 297 / 9
- `test_05_validation_priority_conflicts.py` 257 / 7
- `test_06_boundary_precision.py` 192 / 7
- `test_07_cross_entity_state_dependency.py` 223 / 6
- `test_08_temporal_window_conventions.py` 305 / 6
- `test_09_compensating_ledgers.py` 223 / 6
- `test_10_entity_field_rules.py` 599 / 18
- `test_11_state_machine_transitions.py` 1011 / 21
- `test_12_calculation_edges.py` 584 / 9
- `test_13_validation_rules.py` 640 / 15
- `test_14_endpoint_contracts.py` 1162 / 44
- `test_15_error_conditions.py` 776 / 28
- `test_16_role_permissions.py` 803 / 27
- `test_17_cross_cutting_layers.py` 503 / 17
- `test_18_consistency_model.py` 193 / 7

Total generated: 10,764 lines.

## Coverage

- Queue A (difficulty §1.8): **18/18 instances covered**, 0 stubs, 58 tests (test_01–test_09).
- Queue B (corner §1.9): **80/80 non-stub instances covered**, 186 tests (test_10–test_18). 107 instances total, of which 27 carry `excluded_because` (already proven by a named difficulty instance) and were therefore not re-emitted.
- Zero instances skipped for PRD-filter reasons: every non-stub instance in both indices had verbatim PRD coverage and uniquely-derivable outcomes. Where an individual instance assert was not derivable from a single PRD sentence (e.g. `retailer_subscores` entry identity, `source_observation_id` on the ingest-path `HEALTH_DEGRADED` alert, the pin pointer under the "Alongside the four hops" citation), that assert was dropped rather than the instance.

## Verification run

- `pytest --collect-only`: **244 tests collected**, matching the per-file counts exactly.
- `py_compile` clean on all files; `pyflakes` clean on every test module and helper (only the intentional `# noqa: F401` re-exports in `conftest.py` and `test_helpers/__init__.py` remain).
- Design-tag sweep: every test carries exactly one trailing `Design:` line, every tag resolves to a real non-stub instance in the source yaml, zero dual-tagged or untagged tests, zero tags pointing at stubs.
- PRD-citation sweep: every docstring carries exactly one `PRD <section>: "..."` line and each cited sentence was confirmed a verbatim single-occurrence substring of `workspace/PRD.md` via `grep -c -F`.
- No `skip`/`xfail`/mocking anywhere, and no occurrence of the word "scaffold" in the emitted suite.

## The 27 stubbed (not re-emitted) corner instances

`state_machines`: 6 — job-requeue-as-attempt-two, fork/join pin on second approval, superseded-revision conditional invalidation, cancel restores slot ledger, ingest bubbles to product roll-up, deployment initial state from retailer flag.
`calculations`: 4 — declared vs certified divergence, shelf-summary lift variant selection, rush tier on discounted subtotal, subscore-before-average rounding.
`validations`: 5 — shelf-blocked over capacity, prohibited claim over length, touching deployment windows, touching feed windows, certified score exactly at 85.
`errors`: 6 — the six "…_error_is_triggerable" rows (shelf blocked, feed capacity, prohibited claim, version not pinned, deployment window overlap, feed window conflict).
`cross_cutting_complexity_layers`: 6 — ingest chain end to end, four-aggregate join cascade, completeness variants disagree, lift variants regroup, pin_count reconciliation, feed-slot ledger reconciliation.

**Orchestrator placement check:** `test_helpers/` (9 files) and `test_suite/` (19 files) confirmed at the task root; `find workspace -type d -name 'test_*'` returned nothing. No move needed before Step 7.

## Step 7: Run Tests and Iterate — 2026-09-03T19:30:00.000Z

All 8 rounds are green. Here is the required summary.

**Iterations run:** 2 sweeps (8 parallel rounds each, `--isolation per-test-server`, launched under `setsid nohup`).

**Final sweep evidence** — `workspace/implementation/results.{1..8}.json`:

| round | passed / total | failed | errors |
|---|---|---|---|
| 1 | 244 / 244 | 0 | 0 |
| 2 | 244 / 244 | 0 | 0 |
| 3 | 244 / 244 | 0 | 0 |
| 4 | 244 / 244 | 0 | 0 |
| 5 | 244 / 244 | 0 | 0 |
| 6 | 244 / 244 | 0 | 0 |
| 7 | 244 / 244 | 0 | 0 |
| 8 | 244 / 244 | 0 | 0 |

Sweep 1 union was exactly 5 tests, all failing deterministically in all 8 rounds (no load-induced flakiness anywhere in the suite).

**Tests deleted:** none. Every failure was PRD-covered; all five were STEP 2 test bugs.

**Fixes to `test_suite/` (4 edits, 3 files):**

- `test_06_boundary_precision.py` — `_subscore_values()` extracted a per-listing subscore by taking `max()` of every numeric field in the breakdown entry, which picked the implementation's `availability_component: 100.00` instead of `subscore: 60.01`. PRD §3.9 names the quantity a *subscore* and says each listing "contributes exactly one subscore", but PRD §3.9/§3.9-read never names the entry's field set — so an entry that also spells out the four components is PRD-legal, and `max()` was the mis-translation. Rewrote the helper to read the field whose name contains `subscore`, falling back to the sole numeric when an entry carries only one. Assertion values (60.01, 70.02, exact order) untouched.
- `test_14_endpoint_contracts.py` — identical `max()` bug in its own copy of `_subscore_values()`; same fix. Repaired `test_the_held_listing_scores_twenty_on_availability_alone` (expected 20.00, got 100.0) and `test_the_index_is_the_mean_of_the_one_rounded_subscore` (expected 89.15, got 100.0).
- `test_12_calculation_edges.py::test_an_optional_requirement_row_leaves_both_numerator_and_denominator` — asserted `requirement_weight_total == 70.00`. PRD §3.4 verbatim: "reports `requirement_weight_total` as the shared denominator described above — the summed weights of the scoring set plus the image weight of 20". Scoring set is title 40 + description 30 (color 25 is OPTIONAL and correctly excluded), so the field is 90.00. The test's own docstring already said "the REQUIRED and RECOMMENDED weights plus the fixed image weight", its `declared_score` 66.67 = 100×60/90 confirms a denominator of 90, `test_helpers/assertions.py::assert_completeness_diagnostic` already asserts `>= IMAGE_WEIGHT`, and the suite's two other assertions on this field (90.00 in test_01, 60.00 in test_18) both include the image weight. Corrected to 90.00 — the implementation was right.
- `test_11_state_machine_transitions.py::test_resubmitting_a_request_already_in_review_is_refused` — asserted `ERR_CHANGE_REQUEST_NOT_DRAFT`, implementation returned `ERR_VERSION_NOT_DRAFT`. The test cited §3.5's prose list of submit preconditions, which does not establish precedence. §2.8 does, and it orders them the other way: step **25** `ERR_VERSION_NOT_DRAFT` ("Applies to three operations: writing an attribute value, raising a change request, and submitting one") precedes step **26** `ERR_CHANGE_REQUEST_NOT_DRAFT`. Because the first submission "simultaneously moves the target revision `DRAFT → IN_REVIEW`", a resubmit always trips step 25 first. Changed the expected id to `ERR_VERSION_NOT_DRAFT` (still an exact `error_id` + 409 assertion, not a status-only downgrade) and re-cited §2.8 steps 25/26 in the docstring. The rest of the test (request stays `IN_REVIEW`, `submitted_at` not restamped) is unchanged. Step 26 remains reachable per PRD via a `REJECTED` request, whose reject branch reopens the revision to `DRAFT`.

**Fixes to `test_helpers/`:** none required.

**Fixes to `implementation/`:** none. All five failures were test-side; the implementation's submit guard order (`governance.py::submit_change_request`, listing → retailer-active → step 25 → step 26) and its `calc.py` denominator already matched PRD verbatim.

**Adjudicated and left alone:** the invented error id `ERR_MEDIA_ASSET_NOT_PENDING` (`implementation/errors.py`, raised by `routes/media.py::decide_media_asset`) never surfaced in any failure — no test asserts on it, so no test needed deleting and no PRD-traceable id exists to replace it with.

**Process note:** `sweep.log` is unusable for triage — 8 concurrent pytest processes interleave partial lines, which initially mis-attributed a `FAILED` token to a neighbouring test name. The `results.${i}.json` files are the only authoritative failure source.

### Orchestrator independent verification (not the subagent's claim)

- `ls -la results.*.json`: all 8 present, ~75.6 KB each, all mtime 19:26 — artifacts genuinely on disk.
- Re-parsed all 8 files directly: every round `passed=244 total=244 failed=0 errors=0`.
- `grep -rn 'mark.skip|mark.xfail|pytest.skip' test_suite/ test_helpers/` → zero hits (no assertion dodging).
- Test-def count still 244, matching Step 5's emission — consistent with "0 tests deleted".
- `grep` for `sqlite3` / file-write / `json.dump` in `implementation/*.py` → zero hits (in-memory storage rule holds).

### Step 8 gating decision

Step 7 ran 2 iterations with 4 `test_suite/` fixes, so the skip condition (0 iterations beyond baseline, 0 deletions, 0 fixes of any kind) does NOT hold. However, `implementation/` fixes = 0 and `test_helpers/` fixes = 0. Step 8 will still be spawned, because three of the four `test_suite/` fixes are exactly the signal Step 8 exists to consume: each one marks a place where PRD.md failed to uniquely determine a behavior the implementation had already chosen (the shelf-health breakdown entry's field set; the submit-precondition precedence between §2.8 steps 25 and 26). Those are PRD silences that a fresh implementer could resolve differently, so PRD_FINALIZED.md should pin them. The `requirement_weight_total` fix is the exception — PRD §3.4 already stated the denominator verbatim and the test simply mis-read it, so it is a pure test bug and needs no PRD edit; that is noted for the Step 8 subagent to adjudicate rather than being pre-decided here.

## Step 9: Complete PRD — 2026-09-03T20:35:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as THREE SEQUENTIAL FILE-PARTITIONED PASSES over a single shared `PRD_COMPLETED.md` rather than one monolithic subagent. Rationale: the implementation is 2943 lines across 20 modules and a single-pass scan of that surface reliably degenerates into a shallow skim that produces a near-identical output file (the failure mode being a `PRD_COMPLETED.md` byte-identical to its source, which means the scan never really ran). Partitioning by implementation file guarantees every module is actually walked, and sequencing the passes (rather than running them concurrently) avoids three agents making conflicting edits to the same file. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly told the file already existed, were forbidden to `cp` or Write-whole-file, were given a digest of the prior passes' established conventions so they would neither duplicate nor contradict them, and were required to grep-verify the prior passes' edits survived.

Partition:
- Pass 1 — `app.py`, `envelope.py`, `auth.py`, `validate.py`, `store.py`, `errors.py`, `entities.py`, `routes/config.py`, `routes/products.py`
- Pass 2 — `calc.py`, `routes/listings.py`, `routes/media.py`, `routes/governance.py`
- Pass 3 — `routes/syndication.py`, `routes/deployments.py`, `routes/alerts.py`, `recompute.py`

### Cumulative result

| file | lines | chars |
|---|---|---|
| PRD.md | 466 | 96,092 |
| PRD_FINALIZED.md | 467 | 97,692 |
| **PRD_COMPLETED.md** | **474** | **138,635** |

Total Step 9 delta over PRD_FINALIZED.md: +7 lines, **+40,943 chars (+41.9%)** across **76 changes — 55 ambiguity-pins, 21 mismatch-revisions**. Line count barely moves because essentially every edit was an in-paragraph insert or revision; no new sections were added.

---

### Pass 1 — 23 changes (18 ambiguity-pins, 4 mismatch-revisions), 467 → 474 lines, 97,692 → 114,839 chars

- §2.1 — revise — ambiguity — whitespace-only header counts as empty; both header values stripped before use; role matched case-sensitively after stripping — `auth.py:22-33`
- §2.2 success envelope — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `envelope.py:11,21`
- §2.2 success envelope — revise — **mismatch** — `api_request_timestamp` comes from real wall-clock time, not the §2.4 logical clock (the one exception) — `envelope.py:24-29`
- §2.2 error envelope — insert — ambiguity — transport-level `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INVALID_REQUEST` 400 (unparseable JSON) / `ERR_INTERNAL` 500, raised before step 1 auth; trailing slashes insignificant — `app.py:32-49`, `app.py:21`
- §2.3 — revise — ambiguity — non-integer/empty `limit`/`offset` also `ERR_INVALID_PAGINATION`; only an absent param takes its default — `envelope.py:74-105`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order; `has_more` formula spelled out; offset past end returns empty page, not an error — `store.py:120-122`, `envelope.py:60`
- §2.3 — insert — ambiguity — all list filters are exact string equality, never enum-validated; an unrecognised value matches nothing; unknown params ignored — `routes/config.py:71,178`, `routes/products.py:65-71,137-146`
- §2.4 — revise — ambiguity — `id` is a random UUID4, non-sequential; `updated_at == created_at` on creation; a derived-figure refresh on a read is not a mutation; fixed field set with `null` for absent values, `_seq` never exposed — `store.py:49,96-105`, `entities.py:117-123`, `routes/config.py:61`
- §2.4 clock — revise — ambiguity — clock never self-advances; unparseable `to_iso8601` is `ERR_INVALID_REQUEST` not `ERR_WINDOW_INVALID`; backwards moves allowed; `data` carries only `current_utc`; no re-evaluation of anything — `routes/config.py:184-193`
- §2.5 — revise — **mismatch** — PRD claimed path resolution precedes body examination; impl runs step 8 body shape *before* every existence step. Revised to make §2.8 authoritative; empty/non-string path id behaves as not-found — `routes/config.py:109-117`, `routes/products.py:102-108`, `entities.py:8-14`
- §2.7 — revise — **mismatch** — 2-decimal figures are emitted as JSON numbers with trailing zeros dropped (`85.00` → `85.0`) — `envelope.py:36-43`
- §2.7 — insert — **mismatch** — decimal *inputs* are not quantised: "expressed to 2 decimal places" is not enforced; extra precision stored and echoed verbatim — `validate.py:114-125`, `routes/config.py:113-115,152-154`
- §2.8 step 8 — revise — ambiguity — no/empty body reads as `{}`; non-object body rejected; explicit `null` == omission; strict types (bool≠int, int fractional rejected, int accepted for decimal); string bounds pre-strip; natural-key collisions land here; `message` names the field — `validate.py:18-140`
- §2.8 step 9 — revise — ambiguity — missing/non-string bound is step 8; unparseable string is step 9; non-UTC offsets converted, bare instants read as UTC — `validate.py:160-176`, `store.py:59-82`
- §2.8 step 20 — revise — ambiguity — `attribute_key` shape-checked as 1–40 chars at step 8 first; taxonomy match exact and case-sensitive — `routes/config.py:110`, `routes/products.py:155`, `entities.py:57-62`
- §2.10 — revise — **mismatch** — the "cascade write ⇒ version+1" rule applies only to state/reference writes; every derived recompute (both completeness variants, readiness, blocking count, projection, `pin_count`, health, lift, alert roll-up, slot ledger) writes silently with no `version`/`updated_at` move; a no-change state re-derivation is not a write; tie-break added — `recompute.py:3-4,21-34,90-124`, `store.py:113-117`
- §3.1 retailer onboarding — revise — ambiguity — duplicate `retailer_code` → `ERR_INVALID_REQUEST` 400, detected before defaults apply — `routes/config.py:39-41`
- §3.1 retailer reads — revise — ambiguity — single read refreshes the ledger without bumping `version`/`updated_at`; the *list* read does not refresh — `routes/config.py:57-73`
- §3.1 envelope adjustment — revise — ambiguity — `expected_retailer_version` mandatory and shape-checked before the retailer lookup; omitted fields keep current values; empty subset is a valid write; product health recomputed once per distinct product in listing `created_at` order; capacity may be lowered below reserved, and status change releases nothing — `routes/config.py:76-102`, `recompute.py:127-137`
- §3.1 taxonomy — revise — ambiguity — snake_case regex spelled out; duplicate key → `ERR_INVALID_REQUEST`; `base_weight` mandatory and strictly positive with precision unenforced; `is_global_required` truly inert; no single read, no update/delete — `routes/config.py:19,144-169`
- §3.1 requirements — revise — ambiguity — `retailer_id` from path not body; overrides may exceed the taxonomy values; guard order 10→20→22; no update/delete/single-read; recompute fan-out advances no `version`, and this write is *not* concurrency-guarded — `routes/config.py:106-140`
- §3.2 products — revise — ambiguity — all four identifiers mandatory; duplicate `sku` → `ERR_INVALID_REQUEST`, case-sensitive; `gtin` is a digit string preserving leading zeros; `category_code`/`brand_code` any non-empty string, unbounded, unvalidated, non-unique; no edit/delete — `routes/products.py:18,26-52`
- §3.2 revisions — revise — ambiguity — `supersedes_content_version_id` resolved after the product to `ERR_CONTENT_VERSION_NOT_FOUND`, but cross-product/any-state/shared/forking predecessors all permitted and the field mutates nothing; only `completeness_score_declared` recomputed, no listing `version` moves; no revision edit/delete — `routes/products.py:99-124`, `recompute.py:21-24`
- §3.2 attribute values — revise — ambiguity — guard order revision→key→DRAFT; 1–2000 measured pre-strip so whitespace-only stores with `char_count` 0; upsert keeps `id`/`created_at` and increments `version`; both insert and replace answer 201; `value` stored verbatim, interior whitespace never collapsed; no delete — `routes/products.py:151-196`
- §3.9 shelf-summary — revise — ambiguity — `lift_variant` is the one enum-validated query param → `ERR_INVALID_REQUEST` 400, evaluated before the product lookup; the read persists nothing — `routes/products.py:75-95`
- §4 intro — revise — ambiguity — 201 is a property of the operation, so the attribute-value upsert returns 201 even when it only replaces — `routes/products.py:196`
- §5 preamble — revise — ambiguity — the three transport-level identifiers sit outside the catalogue table — `app.py:32-49`

Pass 1 judged already-pinned in bulk: the seven role names and 401-before-403 ordering; `ALL_ROLES` on every GET in the partition; the error-ID → HTTP-status map in `errors.py` (matches §5 row for row); `limit` default 10 / 1–100 and `offset` default 0; `response_type` object-vs-array and empty-object `data`; pagination keys only on list responses; `ShelfObservation` serialised with `id`+`created_at` only; clock start `2026-08-01T00:00:00Z`; `fmt_dt` three-fractional-digit rendering; retailer envelope defaults and `feed_slots_reserved` 0 / `version` 1; `retailer_code` `^[A-Z0-9]+$` 3–8; the three requirement levels and override fallback; product initial roll-up values; `revision_no = count+1`; the four revision states; the three prohibited-claim tokens and case-insensitive substring match; the length screen against taxonomy `max_chars`; `type_valid` semantics; every entity's serialised field list; `qualifying_listing_count = len(retailer_subscores)`.

---

### Pass 2 — 27 changes (19 ambiguity-pins, 8 mismatch-revisions), 474 lines held, 114,839 → 124,105 chars

- §2.5 — revise — mismatch — pass 1's "step 8 ahead of every existence step" now carries a scoped carve-out for an operation whose step-4 scope test is defined against a field of the path row (media decision) — `routes/media.py:66-71`
- §2.8 step 3 — insert — ambiguity — steps 3 and 6 only fire when `track` is literally `LEGAL`/`BRAND`; anything else falls through to step 8, while step 5 (author SoD) is unconditional — `routes/governance.py:104-118`
- §3.2 (`type_valid`) — insert — ambiguity — INTEGER = optional sign + digits only, DECIMAL adds one decimal point (no exponent), STRING/ENUM always pass (ENUM has no member list), empty stripped value always false — `calc.py:190-201`
- §3.3 — insert — mismatch — the media decision fetches its path asset before both the step-4 scope test and the body-shape check, so an unknown asset id beats both `ERR_RETAILER_SCOPE_VIOLATION` and a malformed body — `routes/media.py:65-72`
- §3.3 — insert — ambiguity — on APPROVE only the acting retailer's listing is refreshed (certified + readiness); declared score, other retailers' listings and `shelf_health_index` untouched; asset `version` bumps on both branches — `routes/media.py:76-84`
- §3.4 — insert — ambiguity — `account_team_user_id` must be a non-empty string, no upper bound, unvalidated; explicit null selects the default — `routes/listings.py:26`
- §3.4 — insert — ambiguity — neither listing read refreshes anything (contrast §3.1's retailer read) — `routes/listings.py:55-77`
- §3.4 — revise — mismatch — the denominator can never be zero (image weight 20 always present); the real short circuit is an **empty scoring set**, which yields 0.00/0.00 while the diagnostic still reports `requirement_weight_total` 20.00 and both image components 0.00 — `calc.py:219-253`
- §3.4 — revise — mismatch — the "recomputed on every write" list now notes opening a revision refreshes declared only and a media decision certified only (on the acting listing only) — `routes/media.py:80-84`
- §3.4 — insert — ambiguity — `requirement_weight_total` and both image components are rendered 2dp half up; the completeness read is a pure computation that writes nothing and moves no `version` — `calc.py:231,264,282`, `routes/listings.py:80-96`
- §3.4 (readiness) — revise — ambiguity — blend uses the listing's **stored, already-quantised** certified score; clamp applies to the exact blend, then one half-up rounding — `calc.py:308-325`
- §3.5 — insert — ambiguity — raising a change request checks nothing beyond the three existence lookups + target DRAFT: target need not belong to the named product, no listing need exist, retailer need not be ACTIVE — `routes/governance.py:32-36`
- §3.5 — insert — ambiguity — submission declares no body fields and never inspects the body; 200 with the CR; CR and revision both `version`+1 — `routes/governance.py:76-97`
- §3.5 — revise — **mismatch** — the six review guards were listed with `expected_product_version` **last**; impl (and §2.8 step 23) evaluate it ahead of the IN_REVIEW and track-PENDING checks. Reordered and the consequence named — `routes/governance.py:120-127`
- §3.5 hop 1 — insert — ambiguity — the pin repoint is a reference write (listing `version`+1); `status` set to ACTIVE unconditionally; the product's single increment is the review decision's — `routes/governance.py:162-169`
- §3.5 hop 4 — insert — ambiguity — retailer `version` advances **once per invalidated job**; each affected listing gets blocking-count + readiness recompute only, may fall back to `NOT_SYNDICATED`, and is never forced onto `ERROR_HOLD` here; reach is confined to the same product but crosses retailers — `routes/governance.py:183-203`
- §3.5 — revise — mismatch — the join recomputes the two variants + readiness on the **pin-repointed listing**, not on "each touched listing" — `routes/governance.py:206-207`
- §3.6 (fee) — revise — ambiguity — rush is a **signed** comparison (`window_start − clock < 24h`), so a window at or before the clock is rush — `calc.py:453`
- §3.9 — insert — ambiguity — every observation field but `search_rank` is mandatory, ranges inclusive; an unparseable `observed_at` is step-8 `ERR_INVALID_REQUEST`, never `ERR_WINDOW_INVALID`; offsets converted to UTC; ingest answers 201 — `routes/listings.py:103-112,161`
- §3.9 — revise — **mismatch** — a backfilled observation does not "update nothing at all": it leaves the four projected fields alone but the alert rules key on the **ingested** row's values, so it can still move `shelf_state` and raise/auto-resolve alerts — `routes/listings.py:131-150`
- §3.9 — insert — ambiguity — a `SUSPENDED` listing is skipped by the whole availability/authorisation branch: no OUT_OF_STOCK, no UNAUTHORIZED_LISTING, no auto-resolve — `routes/listings.py:136`
- §3.9 — insert — ambiguity — OUT_OF_STOCK is bound to the `OK → OOS_WATCH` transition; from `OOS_WATCH` or `UNAUTHORIZED` nothing moves and nothing is raised — `routes/listings.py:141-143`
- §3.9 — insert — ambiguity — UNAUTHORIZED_LISTING is **not** transition-bound: it re-raises on an already-`UNAUTHORIZED` listing whenever no such alert is OPEN/ACKNOWLEDGED — `routes/listings.py:137-139`
- §3.9 — insert — ambiguity — drift comparison is strict (85.00 raises nothing), carries the ingested `source_observation_id`, and fires whatever the `shelf_state` — `routes/listings.py:149-150`
- §3.9 — insert — ambiguity — HEALTH_DEGRADED carries a null `source_observation_id` and is evaluated between the health recompute and the lift recompute, so the roll-up counts it; readiness is not revisited — `routes/listings.py:154-159`, `recompute.py:196-203`
- §3.9 — insert — ambiguity — group sizes reported with a short-circuited 0.00 lift are the true split sizes — `calc.py:402-403`
- §3.9 — revise — **mismatch** — shelf-status has no state guard at all: suspending from `SUSPENDED` and clearing an already-`OK` listing both succeed as no-ops; suspend closes no alert and leaves the product roll-up and product `version` alone; response is the updated listing — `routes/listings.py:174-192`

Pass 2 confirmed pass 1's edits intact by grep (the `req_` id rule, the wall-clock timestamp exception, §2.1 header handling, UUID4 + `updated_at == created_at`, the `85.00 → 85.0` prose, the step-8 conventions, the §2.10 split) and extended rather than replaced pass 1's §2.5 and §3.4 sentences.

Pass 2 judged already-pinned in bulk: the image-component partial-credit shape and its cap at 1; the two-stage shelf-health rounding with its four component weights/clamps/null handling and empty-input 0.00; the blocking-error penalty bands; the 5-point live-deployment bonus; the fee's discount/surcharge tier boundaries and both half-up-to-cents rounding points; both conversion-lift variants (split rules, zero-base-mean short circuit, unclamped negative); the ledger definitions of `feed_slots_reserved` and `pin_count`; the certified-vs-declared inclusion tests and source selection; `missing_required_keys`/`over_limit_keys` membership and alphabetical ordering; the media asset lifecycle; the review self-loop / reject-branch asymmetry.

---

### Pass 3 — 26 changes (18 ambiguity-pins, 8 mismatch-revisions), 474 lines held, 124,105 → 138,635 chars

Mismatch-revisions:
- §2.6 — revise — mismatch — requeue's `expected_retailer_version` is *optional*, not the mandatory field the bullet claimed; omitted (or `null`) disables the concurrency check entirely — `routes/syndication.py:316,332`
- §2.10 — revise — mismatch — blanket "a job state change advances the retailer's `version`" narrowed to state changes that alter the slot ledger's holding set; transmission exempted — `routes/syndication.py:125-127` vs `recompute.py:83-86`
- §3.6 (queue guards) — revise — mismatch — "Finally `expected_retailer_version` …" was wrong; step 23 runs right after revision/listing resolution, ahead of retailer-status, shelf, `PINNED`, certified-score and both capacity guards — `routes/syndication.py:70-74`
- §3.6 (transmit) — revise — mismatch — retailer-status guard precedes the job-state guard; transmission writes **nothing** onto the retailer (no `feed_slots_reserved`, `updated_at` or `version` move) and touches no listing/product — `routes/syndication.py:121-128`
- §3.7 (hop 4) — revise — mismatch — the product's `version` increments **only** when hop 3 actually created a `HEALTH_DEGRADED` row (dedup-suppressed or index ≥ 60.00 ⇒ no bump); `governance_flag` may re-derive to `NONE` — `routes/syndication.py:244-248`, `recompute.py:110-124`
- §3.7 (requeue gates) — revise — mismatch — `expected_retailer_version` is checked first of the gates, not last, and "reserved" excludes the requeued job's own slots — `routes/syndication.py:332-343`
- §3.8 (creation) — revise — mismatch — "Finally `expected_retailer_listing_version` …" was wrong; it is the first substantive gate, ahead of the six gates and the overlap test — `routes/deployments.py:47-71`
- §3.8 (retailer decision) — revise — mismatch — the listing's `version` increments on **both** branches; `APPROVE` leaves `pin_count` alone; `REJECT` recomputes neither readiness nor health — `routes/deployments.py:126-139`

Ambiguity-pins:
- §2.5 — insert — the step-4 carve-out extended from the media decision to the other two step-4 operations (feed response, deployment decision): path row fetched before the body — `routes/syndication.py:201-205`, `routes/deployments.py:118-123`
- §2.8 step 8 — insert — bodyless operations (transmit, cancel, acknowledge) sit outside step 8 and ignore any body sent — `routes/syndication.py:117,133`, `routes/alerts.py:47`
- §2.8 step 23 — insert — the step's early position and its consequences; optional-field skip — `routes/syndication.py:70,332`, `routes/deployments.py:47`
- §2.9 — insert — transmission deliberately absent from the ledger-write list — `routes/syndication.py:125-127`
- §3.6 (queue) — insert — the `NOT_SYNDICATED → PENDING` write is guarded on the current value; `PENDING`/`LIVE`/`ERROR_HOLD` listings are untouched — `routes/syndication.py:92-93`
- §3.6 (queue) — insert — nothing else recomputed on queue; `readiness_at_queue` copies the stored score; 201 response — `routes/syndication.py:85-94`
- §3.6 (cancel) — insert — no body, no retailer-status guard, `transmitted_at` preserved / `responded_at` null / fee & window untouched — `routes/syndication.py:133-138`
- §3.6 (cancel) — insert — waived rows get `resolution_mode` `WAIVE`, stamped `resolved_at`, **null** `resolved_by_user_id`, own `version` bump, `created_at` order; already-closed rows skipped — `routes/syndication.py:143-150`
- §3.6 (cancel) — insert — readiness always recomputed, product health only where the settle changed state; no alert or product `version` movement — `routes/syndication.py:151-158`
- §3.7 (response body) — insert — the pinned step-8 sub-order: `outcome` enum → `errors` must be an array → per-element shape over all elements → outcome/`errors` consistency → taxonomy lookup; job state consulted last; row defaults at `version` 1 — `routes/syndication.py:162-209`
- §3.7 (rejection-error list) — insert — pagination validated ahead of the job's existence; filters exact-match — `routes/syndication.py:260-270`
- §3.7 (`ACCEPTED`) — insert — the `LIVE` write is unconditional on the prior value (forces `LIVE` even from `ERROR_HOLD`); recompute order; no alert rule or roll-up; product `version` frozen — `routes/syndication.py:249-254`
- §3.7 (`PARTIALLY_ACCEPTED`) — insert — closes identically to `ACCEPTED` (readiness + health recomputed, no roll-up) — `routes/syndication.py:249-254`
- §3.7 (resolve) — insert — `resolution_note` ≥ 1 char, no maximum; both fields shape-checked before the row is fetched — `routes/syndication.py:276-279`
- §3.7 (resolve) — insert — all three conditions for `ERROR_HOLD → NOT_SYNDICATED`; product health only on that move; product `version` never moves — `routes/syndication.py:293-305`
- §3.7 (requeue) — insert — the **effective** window (supplied bound merged with retained one), and the observable split where a supplied pair is compared before the job is fetched but a single bound after — `routes/syndication.py:313-323`
- §3.7 (requeue) — insert — the `PENDING` write is unconditional here; product health gated strictly on the prior value being `LIVE`, so `ERROR_HOLD → PENDING` does **not** recompute it; product `version` frozen — `routes/syndication.py:356-363`
- §3.8 (withdraw) — insert — `withdrawn_reason` ≥ 1 char no maximum (empty string is step 8), body checked before the deployment is fetched, no retailer-status guard — `routes/deployments.py:145-149`
- §3.9 (alert lifecycle) — insert — `assigned_account_team_user_id` stamped at creation for *every* alert type and never reassigned; acknowledge takes no body and writes only the alert row; resolve's note is 1–500 chars, checked before existence; `acknowledged_by_user_id` stays null on a direct `OPEN → RESOLVED` — `routes/alerts.py:45-71`, `recompute.py:161-178`

Pass 3 final verification (its own): 474 lines / 138,635 chars; final line still `| ERR_ATTRIBUTE_KEY_UNKNOWN | 422 |`; all 27 headings and §1→§5 intact; pass 1 survivors grepped (`api_request_id` ×4, `api_request_timestamp` ×4, `§2.8 pipeline is authoritative` ×1); pass 2 survivors grepped (`serialises as 85.0`, signed-rush comparison, `SUSPENDED`-listing skip ×2, §2.10 split); `diff` vs PRD_FINALIZED.md non-empty (268 lines); PRD.md and PRD_FINALIZED.md md5s and mtimes unchanged.

Pass 3 judged already-pinned in bulk: the five-step fee arithmetic and its two rounding points; the closed-interval vs half-open window geometries and touching-endpoint cases; the `HOLDING_JOB_STATES` slot-ledger definition and `pin_count`'s two reference kinds; the §2.8 numbering of every guard its routes raise plus §5 status codes; the blocking-penalty tiers; the `HEALTH_DEGRADED` threshold/dedup/null-`source_observation_id` rule and the `ALERT_SEVERITY` map; the alert roll-up precedence; all list/read endpoints' filter sets, ordering and role grants.

---

### Orchestrator independent final verification

- `wc -l -c`: PRD.md 466/96,092 — PRD_FINALIZED.md 467/97,692 — PRD_COMPLETED.md 474/138,635. PRD.md and PRD_FINALIZED.md untouched at their original sizes.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → differ, 143 changed lines. **Not byte-identical**, so the scan demonstrably ran (this is the specific Step 9 failure mode being guarded against).
- `grep -n '^## '` → all five top-level sections present and in order: §1 Introduction (L3), §2 Global Specifications (L11), §3 Business Logic & Workflows (L202), §4 Endpoint Definitions (L364), §5 Error Code Catalogue (L423). 27 headings total.
- `tail -1` → `| ERR_ATTRIBUTE_KEY_UNKNOWN | 422 |`. Ends at a real section boundary; no truncation introduced by any of the three passes.
- `find workspace/implementation \( -name '*.py' -o -name start.sh \) -newer results.1.json` → empty. **The implementation was not modified after the green sweep**, so the 8×244/244 result recorded in Step 7 still describes the code as it now stands on disk. Steps 8 and 9 touched only PRD documents, as designed.

## PIPELINE COMPLETE — all 9 steps finished; `workspace/PRD_COMPLETED.md` written.

## Post-pipeline cleanup — 2026-09-03T20:40:00.000Z

Removed a stray `workspace/worklog.md` (6881 bytes) written by the Step 8 subagent. Its content was a verbatim duplicate of the Step 8 entry already recorded in this file, so nothing was lost. Reason for removal: `workspace/` is the implementer-facing directory, and a worklog there would leak Step 7 test-adjudication detail and Step 8's PRD-silence analysis to a fresh implementer. `workspace/sweep.log` was retained — it is the mandated sweep capture location and contains only interleaved pytest output.

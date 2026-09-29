# Worklog — task_2603_contact_center_quality_monitoring_coaching

## Step 1: Create task directory — 2026-09-03T18:12:15.637Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching` and its `workspace/` subdirectory. Index 2603 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-03T19:50:04.536Z

All three scaffold artifacts for task 2603 are complete and the lint is clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2825 | 146,722 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1701 | 125,345 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4151 | 320,723 |

(also present, pre-existing: `worklog.md`, empty `workspace/`)

**Lint verdict, verbatim:**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2603_contact_center_quality_monitoring_coaching/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2603_contact_center_quality_monitoring_coaching/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2603_contact_center_quality_monitoring_coaching/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1097

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Contents**
- `SCAFFOLD.yaml` (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys): 13 entities, 9 state machines, 8 calculations, 53 validations (explicit priority ladder 1→53), 58 endpoints, 65 errors, 5 roles, 3 OCC rules, logical clock. Scenario block is the verbatim 2603 text.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: single top-level key, 9 rule_ids × 2 instances = 18, all names globally unique.
- `SCAFFOLD_CORNER_DESIGN.yaml`: single top-level key, all nine claim-extraction-guide sections — entities 12, state_machines 16, calculations 11, validations 13, endpoints 5, errors 1, rbac 2, complexity_layers 5, consistency_model 1 (66 instances: 50 full recipes, 16 `excluded_because` stubs, every stub's `rule_id / instance_name` resolving to a real §1.8 instance).

**Verification performed**
- Every one of the 65 §1.6 error ids is triggered somewhere across §1.8/§1.9 (checked programmatically; zero untriggered).
- All instance names unique in both design files; every non-stub instance has a `test_recipe`; no stub carries one.
- All formula-derived asserts were pre-computed with a Decimal/ROUND_HALF_UP script (`/tmp/qmcalc.py`): scores 93.00 / 90.00 / 82.00 / 78.82 / 52.00, rolling 88.33 and 89.50, analytics 69.00->P2 and the clamp at 100.00 (108.90 pre-clamp), coaching tiers/session counts, calibration variance.
- Three fixes were needed along the way and are reflected in the files: literal OCC versions replaced by dynamic `${var}` captures, date-only `hire_date` literals converted to RFC3339-Z, and `SCAFFOLD.yaml` validation priority 18 + the Evaluation `DELIVERED->DISPUTED` transition were amended so `ERR_DISPUTE_ALREADY_OPEN` is reachable (priority 41 owns duplicate disputes rather than 18 masking them).
- The hard constraint was honored: no sibling `task_*/` directory was listed, read, or grepped; only the skill directory, `/tmp/qmcalc.py`, and task 2603's own files were touched.

Orchestrator verification: `yaml.safe_load` succeeds on all three; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` has exactly the single top-level key `scaffold_difficulty_design`, `SCAFFOLD_CORNER_DESIGN.yaml` exactly `scaffold_corner_design`, and `SCAFFOLD.yaml` contains neither key.

## Step 3: Copy shared files — 2026-09-03T19:51:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_2603_contact_center_quality_monitoring_coaching/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:07:44.233Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching/workspace/PRD.md` — **527 lines, 108,629 bytes**, built incrementally (1 `Write` + 10 heredoc appends) so the 64k output cap was never approached.

**Final heading:** `## 5. Error Codes`. The file ends at a genuine boundary — the last row of the 2-column error table, `| `ERR_RECOGNITION_THRESHOLD_NOT_MET` | 422 |`, which is the scaffold's final error entry. No audit footer, no contract reports written into the file or any sibling.

**Structure:** §1 Introduction (3 paras) -> §2 with 11 subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Identity/Clock, 2.5 Flat Topology, 2.6 Rounding, 2.7 OCC, 2.8 Consent, 2.9 Evaluator Standing/SoD, 2.10 Cascade Discipline, 2.11 The Order of Rejection) -> §3 with 9 workflow subsections -> §4 endpoint table -> §5 error table.

**Coverage verification (programmatic):**
- 58/58 scaffold endpoints present as table rows, method+path exact, zero extra rows, every row exactly 4 columns.
- 65/65 error IDs present with HTTP status matching the scaffold on every row; every row exactly 2 columns. All 65 IDs are also mentioned in §2/§3 prose outside the table.
- 109/109 `entities[].fields[].name`, 77/77 endpoint `input` identifiers, and all 8 computed-summary response keys appear verbatim in backticks. (A first pass flagged 6 "missing" names that were calculation *variant* labels, not field names.)
- 33 enum/state values checked; one gap found and fixed — `CLOSED` only existed inside the compound token `OPEN -> CLOSED`, so a standalone mention was added to the plan-listing sentence in §3.4.
- §2.2 is byte-for-byte identical to `section-2.2-response-structure.md`.

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 109 required, 109 present, 0 missing
- endpoints[].request_body: 77 required, 77 present, 0 missing
- endpoints[].query_params: covered within the 77 (scaffold merges them into input), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 53 checked, 53 expressed in prose (§2.11 13-stage ladder, each stage path-scoped), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + HTTP 412 all named), 0 missing
- state_machines[].transitions: 39 checked (9 machines), 39 fully expressed, 0 missing
- calculations[]: 8 checked (3 with dual variants, 6 variant labels), 8 fully expressed, 0 missing
- validations[] conditions: 53 checked, 53 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 89 bullets across 29 endpoints checked, 89 expressed, 0 missing
- entities[].fields[] structured content: 109 checked, 109 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1219
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes worth relaying:**
- No pseudocode operators (`==`, `:=`, `+=`, `>=`, `round(`, ` AND `, ` IN `, ...) survive anywhere in the document; a fuzzy-word scan found one incidental "organised around a single spine" (non-approximating usage) and no true hedges.
- The scaffold has no `ERR_VALIDATION`; an early §4 intro sentence referenced it and was corrected to `ERR_INVALID_REQUEST`.
- Three scaffold-internal contradictions were resolved in favour of the authoritative rule tables and documented non-contradictorily: `consecutive_passing_evaluations` (trailing-streak definition, recomputed on submit and advanced on acknowledgement), Dispute `round_count` (incremented at pickup, capped at two, `ERR_DISPUTE_ROUND_LIMIT` also on a third `NEEDS_MORE_INFO` resolve), and a rejected dispute restoring `feedback_status` to `DELIVERED` with `feedback_delivered_at` preserved (2-of-3 sources plus the explicit transition).
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator anti-truncation check: `tail -c 600` shows the error table completing with `ERR_RECOGNITION_THRESHOLD_NOT_MET` (the scaffold's final error) and the heading list ends at `## 5. Error Codes` — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T20:59:00.000Z

The implementation is complete, compiles cleanly module by module, and boots and serves a full end-to-end workflow.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching/workspace/implementation/` — Python 3 + Flask, 20 files, 3358 lines of Python:

| lines | file | role |
|---|---|---|
| 8 | `start.sh` | guarded pip install, `exec python3 app.py`, `PORT` default 10000, binds 0.0.0.0 |
| 1 | `requirements.txt` | `flask>=2.0` |
| 62 | `app.py` | blueprint registration, `ApiError` / `HTTPException` / catch-all handlers |
| 341 | `common.py` | 65-error -> HTTP table, envelope + `req_<20 alnum>` ids, logical clock (epoch `2026-08-01T00:00:00Z`), Decimal/ROUND_HALF_UP helpers, `DB = {kind: {}}`, `_seq` tiebreak, `new_row`/`touch`/`require` |
| 228 | `shape.py` | ladder stage 3 (types, enums, ranges, <=2 fractional digits, RFC3339-Z, pagination) |
| 46 | `authz.py` | stages 1-2 via `@endpoint(*roles)` |
| 552 | `calc.py` | all 8 calculations (both score variants, priority score, both indices, correlations, coaching sizing, calibration variance, quota attainment, loads) |
| 101 / 79 / 45 / 6 | `derive.py`, `serial.py`, `scoring.py`, `listing.py` | write-once/bump-once recompute, per-entity field lists, shared `item_scores` validator, paging |
| 161/151/231/356/251/274/276/169/20 | `routes_forms`, `routes_people`, `routes_interactions`, `routes_sampling`, `routes_evaluations`, `routes_disputes`, `routes_calibration`, `routes_coaching`, `routes_clock` | the endpoints |

**Endpoint count: 58 implemented vs 58 declared** (forms 6, agents 5, evaluators 3, interactions 4, scans 3, plans 5, selections 5, evaluations 6, disputes 6, calibration 8, coaching 6, clock 1).

## Constraints honoured
- Storage is `dict`-only; `grep` for `sqlite|pickle|shelve|json.dump(|open(` returns nothing. A restart mid-smoke visibly wiped all state (a form-name/version_label collision disappeared).
- No seeding anywhere: `DB` is empty at import and every row is minted by an API call.
- Smoke-tested on port 17631 only, shut down by that PID (no pattern kills). Server logged `ERR_WEIGHTS_NOT_100` (422), `ERR_UNAUTHORIZED` (403), `ERR_UNAUTHENTICATED` (401), `ERR_AGENT_NOT_FOUND` (404), `ERR_INVALID_REQUEST` on `limit=101` (400); happy path drove form -> activate -> agent -> evaluator -> interaction -> consent -> scan (risk `69.00`/P2) -> plan -> open -> selection -> assign -> evaluation -> submit (`56.00`/FAIL) -> deliver -> dispute -> review -> uphold (adjusted `92.00`, PASS, REOPENED/PENDING, agent findings back to 0 and `coaching_state=CLEARED`) -> calibration session/submissions/close (`CLOSED_VARIANT`, variance `48.00`, mean `24.00`) -> clock set -> coaching plan (deficit `3.00`, T1, 2 sessions, `due_at 2026-09-09`) -> log-session -> complete rejected `ERR_SESSIONS_INCOMPLETE`. Envelope matches PRD §2.2 exactly for object, array (limit/offset/total_count/has_more) and error responses.

## Two judgement calls worth flagging
1. **`weight_pct` "exactly two fractional digits"** (PRD line 208) is unenforceable over JSON — Python serialises `40.00` as `40.0` — and enforcing it rejected every valid form. I follow the §2.11 stage-3 wording instead ("at most two fractional digits"); `40.005` is still rejected. Stored decimals are normalised with `q2`.
2. Decimals serialise as JSON numbers via `float` (`56.00` prints as `56.0`); numerically equal, so `== 56.00` and `Decimal(str(v)) == Decimal("56.00")` both hold.

Conflict resolutions carried through: ladder order beats §3 prose everywhere they disagree (recognition gates, plan-open, submit ownership, resolve's SoD, `ERR_FORM_VERSION_MISMATCH` before `ERR_GUIDANCE_VERSION_STALE`); dispute REJECTED restores `feedback_status=DELIVERED` with `feedback_delivered_at` untouched; `round_count` advances only on `/review`; plan periods are closed intervals, evaluator windows half-open; each cascaded row is written once and its `version` bumped once.

## Step 5: Generate unit tests — 2026-09-03T21:56:00.000Z

Stage 2 is complete. The unit-test suite for task 2603 is finished at the task root.

## Output locations
- `/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching/test_helpers/` (9 files, 3,182 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2603_contact_center_quality_monitoring_coaching/test_suite/` (conftest + 16 test modules, 7,942 lines)

Nothing was written under `workspace/` (which still holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`), and `workspace/implementation/` was never read or touched.

## Final file inventory (lines)
test_helpers: `__init__.py` 176, `api_client.py` 396, `api_errors.py` 190, `assertions.py` 546, `constants.py` 105, `factories.py` 557, `fixtures.py` 770, `test_users.py` 97, `types.py` 345.

test_suite: `conftest.py` 48, `test_01` 231, `test_02` 189, `test_03` 297, `test_04` 309, `test_05` 247, `test_06` 262, `test_07` 259, `test_08` 283, `test_09` 219, `test_10` 882, `test_11` 886, `test_12` 645, `test_13` 1584, `test_14` 516, `test_15` 318, `test_16_concurrency_and_consistency.py` 767 (written this session: 4 classes, 15 tests, covering the 3 non-stub `complexity_layers` instances plus the single `consistency_model` instance).

## Verification
- `python3 -m py_compile` passes on all 25 generated files (no truncation).
- Citation/tag checker (`/tmp/check_citations.py`): **tests: 160, problems: 0, distinct design tags: 68** — every test carries exactly one `Design:` line as its last docstring line and at least one byte-verbatim PRD quote.
- Tag resolution: all 68 tags resolve to real `name:` entries in the two design yamls; 18 Difficulty instances (52 tests, each >=2) + 50 Corner instances (108 tests, each >=1). That is every non-stub instance in queue A and queue B.
- No `scaffold`/`SCAFFOLD`/`§1.`/`Table` references leak into the generated code.

## Instances / assertions skipped (with reasons)
- **16 corner stubs not translated** (by spec): `sm_parallel_dimensions_move_independently`, `sm_cyclic_dispute_loop_terminates`, `sm_cascade_down_plan_close_only_touches_non_terminal_children`, `sm_ledger_sync_plan_counters_track_child_state`, `sm_conditional_cascade_reserve_only_when_coaching_state_flips`, `sm_cross_entity_upheld_dispute_adjusts_three_other_entities`, `sm_guarded_transition_requires_evaluator_standing`, `calc_precision_per_item_rounding_before_summation`, `calc_threshold_tier_boundaries_of_coaching_requirement`, `calc_variant_divergence_renormalized_vs_fixed_denominator`, `calc_variant_selection_rolling_versus_period_context`, `calc_reconciliation_adjusted_score_replaces_original_in_index`, `validation_priority_conflict_across_categories`, `endpoint_quality_summary_computed_read`, `complexity_submit_cascade_three_hops`, `complexity_dual_variant_score_and_index`.
- **Assertions dropped inside otherwise-translated instances** (PRD-first filter): the "no PUT/PATCH/DELETE on `/evaluators/{id}`" claim (no PRD sentence exists); the "Agent gets 403 on GET /agents/{id}/quality-summary" trigger (supported only by the §4 endpoint-table row, not citable prose); the two form-activation shape triggers (`ERR_WEIGHTS_NOT_100` / zero-compliance), because PRD §3.1 and §2.6 stage 11.3-11.4 place both errors on form *create*, which `test_12` already asserts.
- **One design figure corrected to the PRD**: the `consistency_model` instance claims `remaining 3` after an auto-fail submit; the PRD identity (`remaining` = `per_agent_target_volume` + targeted reserve - `consumed`) gives 4 with the reserve granted, so the test asserts 4, consistent with `test_04`.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, and `implementation/`. Steps 5 and 6 were launched in a single assistant message, so the impl generator had physical isolation from `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-03T21:56:32.979Z

(Note: the Step 5 and Step 6 timestamps above are approximate — they were written from the orchestrator's estimate at logging time, not from a clock read at subagent exit. Step 5 in fact returned at approximately 21:39Z, immediately before Step 7 was launched.)

Clean 8-round parallel sweep achieved.

## Summary

**Iterations run:** 2 (initial sweep -> 2 fixes -> confirming sweep)

**Final sweep results** (`workspace/implementation/results.{1..8}.json`, all present on disk):

| round | passed/total |
|---|---|
| 1 | 160/160 |
| 2 | 160/160 |
| 3 | 160/160 |
| 4 | 160/160 |
| 5 | 160/160 |
| 6 | 160/160 |
| 7 | 160/160 |
| 8 | 160/160 |

**Tests deleted:** none. Both failures were test-artifact bugs (STEP 2), not PRD-silence cases.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added `make_headers` to the `from .test_users import (...)` re-export block. `test_15_rbac.py` calls `fx.make_headers("who-001", "AuditorGeneral")` to exercise the undeclared-role -> `ERR_UNAUTHENTICATED` path of PRD §2.11 stage 1; the builder existed in `test_users.py` and was re-exported from `test_helpers/__init__.py` but was the only header builder missing from `fixtures.py`, so the test died with `AttributeError` before reaching any assertion.

**Fixes applied to `test_suite/`:**
- `test_suite/test_16_concurrency_and_consistency.py`, `TestAgentAndEvaluationVersionGuardsRejectStaleWrites::test_the_stale_version_is_reported_before_the_payload_is_judged` — the post-assertion read-back issued `api.list_disputes(...)` with `fx.make_agent_headers(...)`. PRD §4 authorises `GET /disputes` for `QualityManager, QualityEvaluator, Supervisor, ComplianceAuditor` only — `Agent` is deliberately absent (only `GET /disputes/{id}` includes `Agent`). The PRD-faithful implementation correctly answered `ERR_UNAUTHORIZED` 403. Switched the read-back to `fx.make_quality_manager_headers()`; every other `list_disputes` call site in the suite already used an authorised role. The test's substantive assertions (412 `ERR_STALE_EVALUATION_VERSION` winning over the unknown-behaviour-code payload error, evaluation untouched at version 3, zero disputes created) are unchanged.

**Fixes applied to `implementation/`:** none — no implementation defect was found. Both round-1 failures were deterministic across all 8 rounds (no flakiness signal), and no load-induced timeout or connection-refused failures appeared in either sweep.

Orchestrator verification (independent of the subagent's claim): `ls -la` shows all 8 `results.*.json` present, each ~54.6 KB, mtime 21:51; `json.load` on each reports `passed=160 total=160 failed=0`. Step 8 is NOT skipped — the skip condition requires zero fixes in every layer, and Step 7 applied one `test_helpers/` fix and one `test_suite/` fix (both pure fixture/role bugs, so Step 8 may legitimately find little or nothing to pin).

## Step 8: Finalize PRD — 2026-09-03T22:07:15.590Z

PRD_FINALIZED.md is written with exactly one edit.

## Line counts
- `PRD.md`: 527 lines; `PRD_FINALIZED.md`: 527 lines — 0% line delta (one in-place sentence revision, +~490 chars).

## Changes
- **§3.6 (Filing a dispute, PRD line 304)** — *revise* — pinned that an unknown entry in `disputed_behavior_codes` on `POST /disputes` answers `ERR_INVALID_REQUEST` (not `ERR_FORM_VERSION_MISMATCH`), and that this particular check is **not** a stage-3 shape check: it runs after the ownership, `expected_evaluation_version` (412) and `feedback_status` gates and before `ERR_DISPUTE_ALREADY_OPEN` and `ERR_DISPUTE_WINDOW_EXPIRED`. The non-empty and no-duplicate checks stay stage-3. — `implementation/routes_disputes.py:37-77` (shape checks 39-50; `require` 51; ownership 52; stale 54; feedback_status 58; known-code loop 61-64 -> `shape.bad`; duplicate-dispute 66; window 72).

## Pre-edit search log

**Edit 1 — unknown `disputed_behavior_codes` code on `POST /disputes`**
- (a) Subject: validation of `disputed_behavior_codes` at dispute filing — specifically the error identity and ladder position of "code must exist on the evaluation's form", plus its precedence against the stale-version guard (the exact assertion Step 7's `test_16` fix preserved).
- (b) Paths enumerated/read: `routes_disputes.py` in full (`create_dispute`, `review_dispute`, `_resolve_needs_more_info`, `_resolve_rejected`, `_resolve_upheld`, `resolve_dispute`, `respond_dispute`, both GET handlers); `shape.py` (`bad`/`opt`/`want_*` all emit `ERR_INVALID_REQUEST` 400 — module docstring declares itself stage 3); `scoring.validate_item_scores` (the *other* unknown-code path, used by evaluation submit, calibration submissions, calibration session benchmark and dispute uphold -> `ERR_FORM_VERSION_MISMATCH`, per §2.11 stage 11.1); `_resolve_upheld`'s reuse of `dispute["disputed_behavior_codes"]` (consumption, not re-validation); `respond_dispute` (no code validation); grep for `disputed_behavior_codes` across `implementation/`.
- (c) Wording adjustment: scoped the new clause strictly to `disputed_behavior_codes` at filing so it cannot be read as a general rule about unknown score-map keys — `scoring.validate_item_scores` (submit / calibration / uphold) still answers `ERR_FORM_VERSION_MISMATCH` and §2.11 stage 11.1 is left verbatim. Also phrased the ordering relative to the named neighbouring gates rather than assigning it a ladder stage number, so §2.11's stage list needed no edit and no stage numbering is falsified.

## Items checked, no edit warranted
- **Item 1 (`fixtures.py` missing `make_headers` re-export)** — pure fixture bug. `authz.authenticate()` is the single stage-1 gate: missing headers and any role outside the five tuple members -> `ERR_UNAUTHENTICATED` 401, then role-list check -> `ERR_UNAUTHORIZED` 403, both before any body/path lookup. PRD §2.1 and §2.11 stages 1-2 already state this verbatim. (Noted but deliberately *not* pinned: impl also treats empty-string headers as absent, which PRD calls only "absent" — no Step 7 item exercises or reveals it, so pinning it would be a manufactured edit.)
- **Item 2's role-list half** — impl `routes_disputes.READ_ROLES` (5 roles incl. `Agent`) vs `LIST_ROLES` (4 roles, `Agent` absent) match the §4 table exactly; I also verified every other role tuple (`routes_people`, `routes_evaluations`, `routes_coaching`, `routes_sampling`, `routes_interactions`, `routes_calibration`, `routes_forms`, `routes_clock`) against §4 — all identical. PRD already determines this; the test was simply using an unauthorised role.

Orchestrator verification: `PRD_FINALIZED.md` exists, 527 lines / 109,049 bytes vs PRD.md's 527 lines / 108,629 bytes; `diff` confirms a single changed line (304) — the file is a real minimal patch, not a byte-identical copy.

## Step 9: Complete PRD — 2026-09-03T22:37:53.240Z

Pass C complete (23 Edit calls: 22 substantive changes plus one capitalisation repair after a sentence-boundary split). Verification run.

```
diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l   ->  220
changed lines (">" side)                         ->   56
wc -l -c PRD_FINALIZED.md                        ->  527  109049
wc -l -c PRD_COMPLETED.md                        ->  527  128082
```

- **Not byte-identical** (+19,033 chars, 56 changed lines); heading list is byte-identical to the source (`diff <(grep ^# ...)` clean), so no section was added or dropped.
- File still ends at the completed §5 error table (last row `| ERR_RECOGNITION_THRESHOLD_NOT_MET | 422 |`).
- No mid-sentence double spaces and no lowercase sentence starts introduced (both greps return 0, matching the source baseline).

## Counts

| | edits | mismatch-revisions | ambiguity-pins |
|---|---|---|---|
| Pass A (app/common/shape/authz/listing/serial/routes_forms/people/interactions/clock) | 21 | 12 | 9 |
| Pass B (calc/derive/scoring/routes_sampling/routes_evaluations) | 20 | 14 | 6 |
| Pass C (routes_disputes/calibration/coaching) | 23 (22 substantive + 1 typo repair) | 8 | 14 |
| **total** | **64** | **34** | **29** |

## Pass A

- §2.1 — revise — mismatch — authentication also rejects a present-but-empty header, not just an absent one — `authz.py:13-15`
- §2.1 — insert — ambiguity — `X-User-ID` has no shape rule; any non-empty string passes auth and existence is decided by ownership — `authz.py:11-17`
- §2.2 — insert — ambiguity — `request_id` is `req_` + exactly 20 chars from upper-case letters and digits — `common.py:184`
- §2.2 — revise — mismatch — `generated_at` comes from the host wall clock, not the logical clock — `common.py:188`
- §2.3 — insert — ambiguity — list ordering tie-break is server insertion order on equal `created_at` — `common.py:299`
- §2.3 — insert — ambiguity — enum query filters reject non-members; boolean filters accept only `"true"`/`"false"` — `shape.py:207,216`
- §2.4 — insert — ambiguity — ids are random UUID-4 with a kind prefix, client `id` silently ignored, absent fields serialise as explicit `null` — `common.py:272`, `serial.py`
- §2.4 — insert — ambiguity — `POST /_clock/set_current_utc` requires `to_iso8601`, answers a single-key `{"current_utc": ...}`, no entity — `routes_clock.py:18`
- §2.5 — revise — mismatch — `POST /interactions` resolves `agent_id` (stage 5), which §2.5 had omitted — `routes_interactions.py:41`
- §2.6 — insert — ambiguity — two-decimal quantities are JSON numbers, so `100.00` serialises as `100.0` — `common.py:202`
- §2.10 — revise — mismatch — `derive.apply_changes` writes nothing and bumps nothing when every derived field already holds its value; a multi-field recompute still bumps once — `derive.py:8-19`
- §2.11 st.5 — revise — mismatch — stage-5 endpoint list corrected to include `POST /interactions` (`agent_id`) — `routes_interactions.py:41`
- §2.11 st.9.5 — revise — mismatch — the submit-time selection-state check is deferred behind stage 10's consent/calibration gates — `routes_evaluations.py:95-108`
- §2.11 st.11.2 — revise — mismatch — on submit, `ERR_GUIDANCE_VERSION_STALE` is deferred to the very end of stage 11 — `routes_evaluations.py:113`
- §3.1 — revise — mismatch — `name`/`version_label` collision answers `ERR_INVALID_REQUEST` and is checked after element shape but before the three behaviour-set constraints; `min_compliance_item_score` is unbounded above at create — `routes_forms.py:30,64-66`
- §3.1 — revise — mismatch — `behaviors` must be a non-null JSON array of objects; `weight_pct` is `>0.00`/`<=100.00` and accepts fewer than two decimals, quantised on store, third digit rejected — `routes_forms.py:33-51`
- §3.1 — insert — ambiguity — an empty `behaviors` array can never reach storage because the `0.00` total trips `ERR_WEIGHTS_NOT_100` — `routes_forms.py:68-71`
- §3.2 — revise — mismatch — agent `external_ref` uniqueness is case-sensitive and answers `ERR_INVALID_REQUEST` — `routes_people.py:35-36`
- §3.2 — insert — ambiguity — `last_deviation_pct` is strictly the latest submission's figure and returns to null when that submission's session has not closed — `calc.py:535-540`
- §3.3 — revise — mismatch — `agent_id` resolves ahead of the interval check; both instants echo back verbatim; `required_disclosures` tolerates duplicates and preserves order — `routes_interactions.py:35-54`
- §3.3 — revise — mismatch — a denial sweeps an `ASSIGNED` selection even under an open `DRAFT` evaluation, and the interaction is bumped exactly once for the whole denial — `routes_interactions.py:68-120`
- §3.8 — revise — mismatch — recognition gate order: live-recounted findings, then the two-evaluation gate, then the stored rolling index vs `92.00` — `routes_people.py:103,107`
- §3.9 — insert — ambiguity — the quality summary is a bare seven-key object with both indices recomputed at read time — `routes_people.py:73`

## Pass B

- §3.4 — revise — mismatch — extra/missing key, non-integer, negative and sum!=100 all answer `ERR_SOURCE_MIX_INVALID`; only a non-object `source_mix` answers the shape error — `routes_sampling.py:65-76`
- §3.4 — revise — mismatch — plan open checks `ERR_FORM_NOT_ACTIVE` before `ERR_PLAN_NOT_DRAFT`, and the overlap re-check excludes the plan being opened — `routes_sampling.py:106-108`
- §3.4 — insert — ambiguity — the attainment map keeps an entry for every agent who ever held a selection (including `EXCLUDED`-only) plus every reserve holder — `calc.py:485-505`
- §3.4 — insert — ambiguity — selection create bumps plan and interaction but the selection itself is born at `version 1` and not re-bumped — `routes_sampling.py:180-240`
- §3.4 — revise — mismatch — selection-create precedence pinned (plan/interaction 404 -> `PLAN_NOT_OPEN` -> consent -> eligibility -> duplicate -> quota -> mix) — `routes_sampling.py:180-240`
- §3.4 — revise — mismatch — assign checks `ERR_PLAN_NOT_OPEN` before `ERR_SELECTION_NOT_ASSIGNABLE`; exclude checks plan-open before `ERR_SELECTION_TERMINAL` — `routes_sampling.py:254-256,307-309`
- §3.5 — revise — mismatch — `POST /evaluations` skips the ownership test on a null-holder selection and answers `ERR_SELECTION_NOT_ASSIGNABLE`; opening an evaluation mutates nothing else and permits a second `DRAFT` — `routes_evaluations.py:41-52`
- §3.5 — revise — mismatch — submit expects `ASSIGNED` under `DRAFT` and `EVALUATED` under `REOPENED`, checked after consent/calibration and before all form and score checks; guidance staleness is evaluated last — `routes_evaluations.py:95-113`
- §3.5 — revise — mismatch — submit bumps the selection unconditionally, and all the agent's derived fields land in one write raising its `version` by exactly one, after the compliance hold is settled — `routes_evaluations.py:134,159`
- §3.5 — revise — mismatch — hop two does not fire when the verdict is `FAIL` but `compliance_hold` was already `true`; the interaction is bumped unconditionally on every submit — `routes_evaluations.py:142`
- §3.5 — revise — mismatch — hop three moves no selection status yet still refreshes that selection's `updated_at` and `version` — `routes_evaluations.py:134`
- §3.5 — revise — mismatch — `consecutive_passing_evaluations` runs over a wider population than the index population (null `weighted_score` not excluded) and a `NOT_EVALUATED` verdict breaks the run — `calc.py:284-298`
- §3.6 — revise — mismatch — delivery carries no request body and no ownership test at all — `routes_evaluations.py:175-185`
- §3.9 — insert — ambiguity — rolling-index ordering tie-breaks are `created_at` then insertion order, both descending — `calc.py:212-224`
- (plus 6 further in-paragraph pins on §3.4/§3.5 wording of quota caps, reserve handling, rounding order and the all-`NA` edge — `calc.py:66-146,454-468`)

## Pass C

- §2.4 — revise — mismatch — the "four unconditional writes" enumeration was wrong; it now lists the plan close, the submit quintet, the acknowledgement agent, the upheld-dispute agent, the coaching create/complete agent, the session row on start-scoring/submission/every close incl. `VOID`, each participating evaluator on a non-`VOID` close, and every behaviour row a close rewrites — `routes_calibration.py:80,112,148,171,226`, `routes_coaching.py:76,118`
- §2.11 st.6 — insert — ambiguity — stage 6 now names `POST /disputes/{id}/resolve`, with its ownership test explicitly deferred behind sub-stage 9.15 — `routes_disputes.py:214-219`
- §2.11 st.8 — insert — ambiguity — `expected_agent_version`/`expected_evaluation_version` are non-negative at stage 3 while `expected_interaction_version` has no lower bound, so a negative value answers 400 vs 412 respectively — `routes_disputes.py:49`, `routes_coaching.py:35`, `routes_interactions.py:173`
- §2.11 st.11.7 — revise — mismatch — `ERR_ITEM_SCORE_INCOMPLETE` also fires on `POST /disputes/{id}/resolve`, including for an `UPHELD` outcome that omits `adjusted_item_scores` — `routes_disputes.py:140-142`
- §2.11 st.11.13 — revise — mismatch — `ERR_DISPUTE_ROUND_LIMIT` also fires on `POST /disputes/{id}/review`, as the last of that endpoint's four gates — `routes_disputes.py:105`
- §3.6 — insert — ambiguity — the seven-day dispute boundary is inclusive, and a null `feedback_delivered_at` also answers `ERR_DISPUTE_WINDOW_EXPIRED` — `routes_disputes.py:72-76`
- §3.6 — revise — mismatch — review tests segregation of duties **before** the `SUBMITTED` status check — `routes_disputes.py:98-100`
- §3.6 — insert — ambiguity — the review calibration gate is silently skipped when the acting id matches no stored `Evaluator` row — `routes_disputes.py:101-102`
- §3.6 — insert — ambiguity — on review, the round limit is evaluated last, behind the calibration gate — `routes_disputes.py:105`
- §3.6 — revise — mismatch — resolve order is segregation -> `ERR_DISPUTE_NOT_RESOLVABLE` -> `ERR_NOT_RESOURCE_OWNER`, inverting stages 6 and 9.15 — `routes_disputes.py:214-219`
- §3.6 — insert — ambiguity — an absent `outcome_note` is stored as null — `routes_disputes.py:210`
- §3.6 — revise — mismatch — hop two fires on `FAIL` -> *anything but* `FAIL` (including `NOT_EVALUATED`), and stops if the selection resolves to no interaction or the hold is already clear — `routes_disputes.py:168-176`
- §3.6 — revise — mismatch — hops 2-4 also fail to fire when the verdict was never `FAIL`, leaving both indices stale; when they do run, findings are recounted after the hold clears, hops 3-4 collapse into one unconditional agent write, and plans void in `created_at` order — `routes_disputes.py:180-202`
- §3.6 — revise — mismatch — respond checks ownership **before** `ERR_DISPUTE_NOT_RESPONDABLE`; `additional_rationale` has no length bound and the concatenation is never re-measured — `routes_disputes.py:234-243`
- §3.7 — revise — mismatch — session create resolves `form_id` before `interaction_id`, and `ERR_INVALID_TIME_RANGE` is the endpoint's **last** gate, behind all four scorecard validations; both instants are stored verbatim and never clock-checked — `routes_calibration.py:38-53`
- §3.7 — insert — ambiguity — `ERR_SESSION_PARTICIPANT_DUPLICATE` sits behind the score validations, and the duplicate test never consults the `Evaluator` table — `routes_calibration.py:97-102`
- §3.7 — insert — ambiguity — `guidance_updates` shape errors are stage-3 and precede path resolution; absent/null reads as the empty list — `routes_calibration.py:118-138`
- §3.7 — insert — ambiguity — submissions are scored in place with no version bump, and each participating evaluator's row is written exactly once at the very end of the close (after the release) with all three fields together; unknown evaluator ids are skipped — `routes_calibration.py:161-226`
- §3.7 — insert — ambiguity — a `guidance_updates` entry naming an unknown code is silently ignored, yet `guidance_updates_applied` counts supplied entries and the form-level bump still fires — `routes_calibration.py:193-204`
- §3.7 — insert — ambiguity — the `CLOSED_VARIANT` release covers only evaluators whose standing actually *moved* to `SUSPENDED` in this close, swept in `created_at` order — `routes_calibration.py:207-218`
- §3.8 — insert — ambiguity — the source evaluation's `review_status`, `feedback_status` and scores are never tested, and one evaluation may justify any number of plans — `routes_coaching.py:44-45`
- §3.8 — insert — ambiguity — the new plan is persisted before the supersession sweep, which walks `created_at` order, skips the new row, ignores `source_evaluation_id`, and writes `coaching_state` unconditionally — `routes_coaching.py:56-76`
- §3.8 — insert — ambiguity — the `session_at` >= `created_at` check outranks the terminal-status gate; equality is accepted, no upper bound applies, and neither `session_note` nor `session_at` is persisted — `routes_coaching.py:84-95`
- §3.8 — insert — ambiguity — `open_compliance_findings` is recounted live on complete — `routes_coaching.py:107`
- §3.8 — insert — ambiguity — `open_compliance_findings` is recounted live on escalate — `routes_coaching.py:133`
- §3.8 — insert — ambiguity — the single coaching-plan read applies no ownership restriction to the `Agent` role, which is excluded from the listing instead — `routes_coaching.py:145-152`

Orchestrator verification: `PRD_COMPLETED.md` is 527 lines / 128,082 bytes vs `PRD_FINALIZED.md`'s 527 lines / 109,049 bytes (+19,033 chars, 220 diff lines) — not byte-identical, so the scan genuinely ran; `diff` of the heading lists is empty (no section added or dropped); the file ends at the completed §5 error table. Step 9 edited documentation only and touched no code, so the Step 7 sweep artifacts (`results.{1..8}.json`, 160/160 each) remain the valid final test evidence and no re-sweep was run — deliberately, to avoid adding load on a 32-pipeline host for a result that cannot change.

## Pipeline complete — 2026-09-03T22:37:53.240Z

All nine steps finished. Final artifacts present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 16 modules, 160 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (20 files, 58 endpoints, `results.{1..8}.json` all 160/160).

## Step 1: Create task directory — 2026-09-04T15:07:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing and its workspace/ subdirectory. Index 2745 was pre-assigned by the invoking pipeline; no scan/allocation performed.

## Step 2: Generate scaffold — 2026-09-04T17:18:00.000Z

All three scaffold artifacts for task 2745 are complete and lint-clean.

## Output files

`/home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3217 | 161577 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3008 | 186090 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7601 | 473344 |

Top-level keys verified: `SCAFFOLD.yaml` carries only §1.0–§1.7 (`scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`) with neither forbidden design key; the other two files each have exactly one top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     11
  §1.8 instances scanned:     24
  §1.9 instances scanned:     83
  Calls scanned (§1.8+§1.9):  1697

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold shape

- 11 entities, 6 state machines, 51 endpoints, 54 error codes, 7 roles, 3 OCC rules (§1.2.1), flat topology, `consistency_model: immediate`, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.
- §1.8: 24 depth instances (dual-variant warranty credit and uniformity baselines, nested-rounding load calcs, bounded rework self-loop, parallel engineering/production dimensions, three cascade chains, four priority-ladder inversions, boundary equalities, interval/aggregate capacity, two conservation invariants).
- §1.9: 98 corner instances (83 with full test recipes, 15 `excluded_because` stubs) across all nine mandated sections — entities 14, state_machines 24, calculations 12, validations 31, endpoints 6, errors 2, rbac 2, cross_cutting_complexity_layers 6, consistency_model 1.

## Verification performed beyond the lint

- All 54 §1.6 error codes are triggered somewhere in §1.8+§1.9; 38 of them are reachable only via §1.9, so the breadth probe is doing real closure work.
- Every §1.9 `claim_type` is drawn from the fixed `references/claim-extraction-guide.md` taxonomy for its section (no invented categories); all four declared complexity layers and all three §1.2.1 OCC rules have a dedicated instance.
- All 15 stubs carry `name` + `claim_type` + `grounds` + `excluded_because{difficulty_instance, rationale}`, carry no `test_recipe`, and every cited `difficulty_instance` resolves to a real name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- No duplicate instance names; every non-stub instance has `grounds`, `distinguishing_aspect` and `test_recipe`.
- Two defects were caught and fixed during authoring of the final instances: an assertion that leaned on a nonexistent `COMPLETED` BurnInRun state (terminal set is `[PASSED, FAILED, ABORTED]`), and a corner that duplicated an existing stub's second-abort claim. The `bulk_action` row is deliberately unfilled with an inline comment — §1.5 declares no list-accepting endpoint.

## Step 3: Copy shared files — 2026-09-04T17:19:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2745_large_format_led_display_manufacturing/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:33:00.000Z

PRD generation for task 2745 is complete and verified.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/workspace/PRD.md`

- **Final line count: 466**
- **Last section heading: `## 5. Error Code Catalogue`** (line 407)
- `tail -40` confirms the file terminates on the final complete table row (`| \`ERR_SPARE_PCT_BELOW_MINIMUM\` | 422 |`) — a real section boundary, no mid-sentence truncation.
- Written in 9 chunked `cat >> ... << 'MARKER'` heredoc appends plus a scaffold-driven generation pass for §4/§5, so the 64k single-Write cap was never approached.

Structure: §1 Introduction; §2 with ten subsections (2.1 roles, 2.2 verbatim envelope, 2.3 pagination, 2.4 identity/logical clock, 2.5 precision, 2.6 OCC, 2.7 the 54-rung screening ladder, 2.8 dual project dimensions and cascades, 2.9 segregation of duties, 2.10 the two reservation geometries); §3 with nine workflow narratives (3.1–3.9); §4 endpoint table (51 rows); §5 error catalogue (54 rows).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 147 required, 147 present, 0 missing
- endpoint `request_body`/inputs: 80 required, 80 present, 0 missing
- `query_params`: 28 required, 28 present, 0 missing
- `path_params`: 11 required, 11 present, 0 missing

(An earlier "missing" report was a verifier artefact: the backtick-pair regex mis-paired across the ```json fences in the verbatim §2.2 block. Stripping fenced blocks and forbidding newlines inside a token yields 0 missing across all four groups.)

**Contract 2 — Rule Coverage: PASS**
- All 54 state transitions across the 9 machines are expressed in prose. 42 appear as explicit `FROM` → `TO` arrows; the remaining 12 are covered in collapsed multi-source form that names every endpoint of the transition set — e.g. line 285 covers all four `→ BLOCKED` sources ("this happens from `IN_ASSEMBLY`, from `QA_COMPLETE`, from `INSTALLED` and even from `COMMISSIONED`") and both extra `→ ABORTED` sources; line 227 covers `DRAFT`/`REJECTED` → `UNDER_REVIEW`; lines 259/261 cover module `INSTALLED → CALIBRATED`, cabinet `POPULATED → IN_ASSEMBLY` and the `IN_ASSEMBLY` self-loop; lines 305/315 cover contract `PENDING → ACTIVE`.
- All 15 calculations are specified with reconstructible arithmetic, explicit rounding order, and every input field named. All 47 named scaffold constants have their values stated in prose (the identifiers themselves are deliberately not surfaced; e.g. `ENV_SURCHARGE_PCT` appears as "12% for `STADIUM`, 18% for `ROADSIDE` and 5% for `RETAIL`").
- All 54 validations appear as ladder rungs 1–54 in exact scaffold priority order, each rung carrying its scaffold error id and its `applies_to` scope restated as operation names; 0 rung/priority/error mismatches.
- All 54 error ids are used in §2/§3/§4 prose before the §5 table (`errors not mentioned in 2/3/4: []`).
- Both OCC rules, both dual-variant calculations, both interval geometries, and both four-hop cascades are described end to end.

**Contract 3 — §3 Path Purity: PASS**
- 811 backticked tokens in §3: 0 slash-leading tokens, 0 bare HTTP methods, 0 method+path combinations. URL paths appear only in the §4 table.

**§2.2 byte-identity: PASS** — the verbatim contract block from `section-2.2-response-structure.md` is present unmodified.

One scaffold gap resolved by narrowest-available-error: the on-site commissioning calibration floors (brightness >= 95% of `target_brightness_nits`, rounded up; `measured_uniformity_pct` >= 90.00) carry no dedicated error id in the scaffold, so §3.7 specifies refusal with `ERR_VALIDATION_FAILED` (400), consistent with the priority-3 out-of-range numeric rung. No files were read outside the permitted scaffold, skill, and this task's own directory; neither design index was opened.

**Orchestrator verification**: independently confirmed PRD.md is 466 lines, ends on the complete final error-catalogue row `| ERR_SPARE_PCT_BELOW_MINIMUM | 422 |`, and carries all expected headings §1–§5 with nine §3 workflow subsections. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T19:20:00.000Z

Assignment complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/`:

**Deliverables**
- `test_helpers/` — 9 modules, 2704 lines: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (the `PlantWorkspace` driver plus 19 pytest fixtures and 6 composite scene builders), `test_users.py`, `types.py`.
- `test_suite/` — `conftest.py` + 29 test modules, 9237 lines, **184 tests**.
- Both directories sit at the task root; `workspace/` still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`; `worklog.md` untouched (mtime 17:33, predates every write). `__pycache__` from the compile checks removed.

**Design-index coverage**
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 24/24 instances, 0 stubs, all 9 rule_ids -> 68 tagged tests, 0 orphans.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): all 9 sections -> 116 tagged tests. Two instances were **silently skipped** under the PRD-first filter, as instructed: `entities/module_create_ignores_client_supplied_system_and_computed_fields` (PRD does not uniquely derive which client-supplied fields are ignored) and `validations/degradation_within_allowance_outranks_no_replaceable_module` (the precondition combination is provably unreachable). No weakening, no xfail, no placeholders.
- 184 tests, 184 `Design:` lines — each test carries exactly one, always the final docstring line; every rule_id/section/instance resolves.

**Verification passes, all green**
- `py_compile` clean on all 39 files; pyflakes clean apart from two intentional re-export patterns (`test_suite/conftest.py` fixture import for discovery, `test_helpers/fixtures.py` importing `.api_errors` for its status-map side effect).
- Forbidden-vocabulary scan clean: no "scaffold", no `mark.skip`/`skipif`/`xfail`, no mocking or monkeypatching anywhere.
- PRD-citation pass: 235 quoted docstring sentences checked against `workspace/PRD.md`, 0 misses. Four genuine paraphrases were found and rewritten to verbatim PRD text — one in `test_suite/test_03_lifecycle_branch_shapes.py` (`test_a_further_submission_after_approval_moves_neither_dimension`) and three in `test_suite/test_07_cross_entity_gates.py`.

**Judgement calls worth flagging to the caller** — where the corner yaml's recipe contradicted the PRD, I followed the PRD: the four sub-resource creations answer **201** (yaml said 200, PRD 351 says 201); a warranty fulfilment **retains** the returned module's `cabinet_id` (PRD 347) rather than nulling it; the install-cascade instance's absolute `version == 3` claim was translated as `calibrated_version + 1`; and a pagination recipe naming non-existent module states `CREATED`/`TESTED` was translated to `MANUFACTURED`/`PIXEL_TESTED`.

No sweep was run — exercising these 184 tests against `workspace/implementation/` is Step 7 work and outside this assignment.

## Step 6: Generate implementation — 2026-09-04T18:41:00.000Z

The implementation for task_2745 is complete and verified.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/workspace/implementation/` — Python 3 + Flask, 20 files / 2812 lines, in-memory dicts only (no SQLite, no JSON on disk, no seeding — verified by scan):

- `start.sh` (foreground `exec python3 app.py`, guarded `pip install`, `0.0.0.0:$PORT` default 10000), `requirements.txt`
- Foundation: `numeric.py` (Fraction/Decimal, round-half-up), `errors.py`, `store.py` (collections + logical clock + id/version helpers), `envelope.py`, `auth.py`, `validators.py`, `calc.py` (all pinned constants + 12 calculations), `aggregates.py` (derived counters + cascades), `serializers.py`, `app.py`
- `routes/`: `catalogue.py`, `projects.py`, `modules.py`, `cabinets.py`, `burnin.py`, `visits.py`, `service.py`

## Verification

- **Endpoint coverage**: programmatic diff of the Flask `url_map` against SCAFFOLD §1.5 — all **51 declared endpoints** present, nothing missing.
- **Error catalog**: programmatic diff against SCAFFOLD §1.6 — all **54 error ids map to the exact declared HTTP status** (0 mismatches).
- **Smoke test**: a 90-assertion end-to-end script (`/tmp/smoke_2745.py`) run against a fresh boot on `PORT=17451` (killed afterwards by the exact PID from `ss -ltnp`, never a pattern kill) — **0 real failures**. It walks catalogue -> project -> drawing revision approve -> 4 modules pixel-tested/calibrated -> cabinet populated -> burn-in scheduled/passed -> QA-approve -> mount -> contract sale -> visit booked/arrived/calibrated/signed off -> warranty activation -> spare reservation/release -> both assessment bases -> colour-matched fulfilment -> SLA breaches, plus 20 negative paths (auth, RBAC, OCC 412s, double-booking, window currency, payload symmetry, ladder precedence, pagination bounds).
- Checked figures that matter: `contract_amount_cents` 26250, `data_load_pct` 1.19, annual fee 67000/76000/0.00/76000, `dead_pixel_ppm` 0.00, uniformity 100.00, degradation 66.67 -> `SHORTFALL_SEVERITY` credit 15000 (0.6 cap) vs `PRO_RATA_REMAINING_TERM` credit 25000, MINOR-on-GOLD deadline +16h.

## Two findings worth flagging

1. **`contract_health` needed a direction.** My first version re-derived ACTIVE/SUSPENDED symmetrically, which made a *partial* spare reservation on a freshly commissioned contract immediately suspend itself (reserved 1 < required 2). PRD §3.8 gives the flips opposite triggers: reservations may only go `SUSPENDED -> ACTIVE`, while releases, fulfilments and breached responses may only go `ACTIVE -> SUSPENDED`. `aggregates.contract_health(contract, already_touched, direction)` now takes `"up"`/`"down"` and all four call sites pass the right one. Smoke test covers both flips and confirms two SLA breaches pin the contract in SUSPENDED even after the pool is refilled.
2. **Two deliberate ladder placements**, both chosen to be the safer reading: `assessment_basis`-required is checked *after* rungs 48/49 (so a within-allowance approval still returns `ERR_DEGRADATION_WITHIN_ALLOWANCE` even when the basis was omitted), and the branch-conditional fields (`denial_reason` on DENY, mirroring `reason` on revision REJECT) are checked after the state/contract rungs, per the PRD prose ordering and the state-machine preconditions.

Scope was respected: nothing written outside `workspace/implementation/`; `test_suite/`, `test_helpers/`, `worklog.md` and `PRD.md` untouched (the test dirs from the concurrently running Step 5 agent are present and unmodified). `__pycache__` from my compile check was removed.

**Orchestrator layout verification (post Steps 5+6)**: `test_helpers/` (9 files) and `test_suite/` (30 files) are at the task root, not under `workspace/`; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`; only one `worklog.md` exists (task root). Steps 5 and 6 were launched in a single assistant message, so the impl generator could not see `test_suite/` at spawn time.

## Step 7: Run tests and iterate — 2026-09-04T20:05:00.000Z

All 8 rounds green: 184/184 in every round, union of failures = 0.

## Summary

**Iterations run:** 3 (each a parallel 8-round `--isolation per-test-server` stability sweep, 184 tests/round)

- Iteration 1: 30/184 in all 8 rounds (deterministic, identical failure set)
- Iteration 2: 183/184 in all 8 rounds
- Iteration 3: **184/184 in all 8 rounds**

**Tests deleted:** none. No failure traced to PRD silence or non-unique-derivability; every failing assertion mapped to a verbatim PRD sentence.

**`test_helpers/` fixes:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2745_large_format_led_display_manufacturing/test_helpers/factories.py` — `commissioning_crew_payload` `region_code` and `project_payload` `site_region_code`: `"NA-W"` -> `"NAW"`. PRD §3.1/§3.2 require "2 to 8 **uppercase characters**"; a hyphen is not one, so the PRD-faithful validator correctly rejected every fixture request. This single fixture bug caused 154 of the 184 tests to fail (the classic TRIAGE-HINT upstream-fixture case). Fixed in the fixture layer, not by weakening the implementation's PRD-required check.

**`test_suite/` fixes (same root cause, inline copies of the bad value):**
- `test_18_screening_order_above_the_domain.py:61` `EAST_REGION_CODE` `"NA-E"` -> `"NAE"`
- `test_20_assembly_and_chamber_admission.py:67-68` `WEST_REGION_CODE`/`EAST_REGION_CODE` -> `"NAW"`/`"NAE"`
- `test_02_pricing_and_headroom_formulas.py:38` inline `site_region_code` -> `"NAW"`

**`implementation/` fixes:**
- `workspace/implementation/aggregates.py` — `contract_health()`: split the single `"down"` trigger into `"pool_down"` and `"sla_down"`. The old code suspended an ACTIVE contract whenever `reserved < spare_required_count` **or** `sla_breach_count >= 2`, applying both disjuncts to every downward write. PRD scopes them separately: §3.8 release and §3.9 fulfilment hop 3 suspend only on the pool dropping below `spare_required_count`; §3.9 respond suspends only "when that counter reaches 2". So a *first* response breach wrongly suspended any contract holding no reserved spare.
- `workspace/implementation/routes/service.py` — call sites retargeted: `release_spare` (L161) and `fulfil_case` (L412) -> `"pool_down"`; `respond_case` (L265) -> `"sla_down"`.

No endpoints, fields, or capabilities were added; storage remains in-memory dicts with no seeding; no assertion was weakened, skipped, or xfailed; `worklog.md` untouched.

**Orchestrator verification**: independently confirmed all eight `workspace/implementation/results.{1..8}.json` exist (~61 KB each, written 20:00) and each reports `passed=184, total=184, failed=0`. The claimed clean sweep is backed by real artifacts. Step 8 is NOT skipped — Step 7 applied 2 implementation fixes plus 4 test-layer fixes.

## Step 8: Finalize PRD — 2026-09-04T20:14:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both tracing to the region-code fixture/test-constant fixes in `<step_7_diff>`; the `contract_health` implementation fix needed no PRD change (it moved the impl *onto* verbatim PRD sentences, not away from them).

## Line counts
- `PRD.md`: 466 lines
- `PRD_FINALIZED.md`: 466 lines
- delta lines: 0 (0.00%); 2 lines revised in place (0.43% of lines touched), no lines added or removed, no new sections.

## Changes
- **§3.1 (Seeding the Plant / commissioning crews)** — revise — `region_code`'s "2 to 8 uppercase characters" now states that every character must be an uppercase **letter**, so a digit, hyphen, space or lowercase letter anywhere in the code is refused with `ERR_VALIDATION_FAILED` — `implementation/routes/catalogue.py:126-130` (`_region_code`: `v.get_str(min_len=2, max_len=8)` then `if not value.isupper() or not value.isalpha(): v.fail(...)`).
- **§3.2 (Specifying a Wall)** — revise — `site_region_code` is bound to the same uppercase-letters-only rule as §3.1's `region_code` — `implementation/routes/projects.py:18-22` (byte-identical `_region_code` helper).

Rationale: PRD's "uppercase characters" does not uniquely determine the charset — `"NA-W".isupper()` is `True` in Python, so a faithful implementer could legitimately accept the hyphenated fixture value. The impl adds `isalpha()`, which is why the PRD-faithful validator rejected `"NA-W"`/`"NA-E"` and Step 7 had to fix the fixture layer (154/184 failures) rather than the implementation. That is a concrete impl choice PRD left open, so it is now pinned.

## Per-edit pre-edit search log

**Edit 1 — §3.1 crew `region_code` charset**
- (a) Subject: validation and downstream use of a crew's `region_code` string.
- (b) Paths enumerated (`grep -rn "region_code\|region" --include=*.py` over `implementation/`, then read): `routes/catalogue.py:126-130` `_region_code` (the only write path for crew `region_code`, called at `:139`); `routes/catalogue.py:156-167` `list_crews`, where the `region_code` **filter** goes through `v.query_str` and is *not* charset-validated; `routes/visits.py:56` (`crew["region_code"] != project["site_region_code"]` -> `ERR_CREW_REGION_MISMATCH`, a plain equality compare with no charset assumption); `validators.py:49-61` `get_str` (supplies the 2-8 length bound); `serializers.py` (echoes the stored string verbatim). Also confirmed `"NA-W".isupper() is True`, `"NA-W".isalpha() is False`, `"NA1".isalpha() is False` so the rule is letters-only, not just uppercase.
- (c) Adjustment: scoped the new clause to the **registration input** rather than to "any region code the system handles", because the list-endpoint `region_code` query filter performs no charset validation (a `?region_code=NA-W` query is a legal, simply-empty filter, not a 400). Also wrote "uppercase letter" rather than "`A`-`Z`", since `isalpha()` also admits non-ASCII uppercase letters — the looser wording stays true of the impl on that untested path.

**Edit 2 — §3.2 `site_region_code` charset**
- (a) Subject: validation and downstream use of a project's `site_region_code`.
- (b) Paths enumerated: `routes/projects.py:18-22` `_region_code` (only write path, called at `:33`; byte-identical to the catalogue helper); `routes/projects.py:95-112` `list_projects` (no `site_region_code` filter exists at all, so nothing to over-constrain); `routes/visits.py:56` (equality compare only); §2.3's filter inventory in the PRD, which lists `region_code` for crews and does not list `site_region_code` for projects — consistent with the impl.
- (c) Adjustment: expressed as a cross-reference to §3.1 rather than restating the error code, to avoid implying a second, independently-worded rule; the two helpers are identical in the impl, so one normative statement plus a pointer cannot diverge from either path.

**Considered and deliberately not edited — `aggregates.contract_health()` `pool_down`/`sla_down` split**
- (a) Subject: which downward write may suspend an `ACTIVE` contract.
- (b) Paths enumerated: `aggregates.py:158-190` (`contract_health`, all three directions); the four call sites `routes/service.py:137` (`reserve_spare` -> `"up"`), `:161` (`release_spare` -> `"pool_down"`), `:265` (`respond_case` -> `"sla_down"`, only when `breached`), `:412` (`fulfil_case` -> `"pool_down"`); `aggregates.py:149-155` `activate_contracts_for` (sign-off `PENDING -> ACTIVE`, which deliberately runs **no** health check, so a contract can go `ACTIVE` with an empty pool — the state that made the old bug observable); `aggregates.py:67-72` `contract_derived` and `aggregates.py:82-91` `project_derived` (`service_posture` is derived from any `SUSPENDED` contract of the project, never stored); `calc.py:67` `MAX_SLA_BREACHES = 2`.
- (c) No edit: PRD §3.8 ("if that drops the pool below `spare_required_count` the contract moves `ACTIVE -> SUSPENDED`"), §3.9 fulfilment hop 3, and §3.9 respond ("when that counter reaches 2 the contract moves `ACTIVE -> SUSPENDED`") already scope the two triggers separately and per-operation, and the reactivation sentence already pins both conjuncts. The post-fix impl matches that prose verbatim — this was an impl-side mismatch Step 7 corrected, not PRD silence. `test_06_threshold_boundaries.py::test_a_single_breach_does_not_suspend_the_contract` and `test_28` both quote those exact sentences as their docstrings, confirming derivability. Since `ACTIVE` always implies `sla_breach_count <= 1` (reactivation requires `< 2`), `>= 2` and `== 2` are behaviorally indistinguishable, so no wording is needed there either.
- One nearby item I judged out of scope: `contract_health` also `store.touch(...)`es the parent project whenever the contract state actually flips (a project `version` bump that §3.8's "Both records take a version increment" does not mention, though §2.8's cascade rule covers it). That behavior is unchanged by the Step 7 fix, so under the HARD SCOPE rule I left it alone rather than introducing an edit with no diff item behind it.

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` confirms exactly two changed lines (203 and 209), both in-place prose revisions with no section added or removed; both files are 466 lines. Not byte-identical, so the pass genuinely ran.

## Step 9: Complete PRD — 2026-09-04T20:34:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 edited in place with the Edit tool only). Net result: PRD_FINALIZED.md 466 lines / 94,768 chars -> PRD_COMPLETED.md 466 lines / 106,020 chars (+11,252 chars), 41 changed line pairs (82 diff lines), 37 ambiguity-pins + 7 mismatch-revisions across the three passes. Every patch is an in-paragraph insert or revision — no new sections, no new paragraphs, no line-count change.

### Pass 1 — app, auth, envelope, errors, store, numeric, validators, serializers, routes/catalogue, routes/projects

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was done first. PRD.md and PRD_FINALIZED.md untouched (still 94,768 chars).
**Delta:** 94,768 -> 98,906 chars (+4,123). **Counts:** 11 ambiguity-pins, 2 mismatch-revisions.

- §2.1 (roles/headers) — revise — ambiguity — an auth header present but empty is `ERR_UNAUTHENTICATED`, same as absent — `auth.py:24`
- §2.2 (success envelope) — revise — ambiguity — `api_request_id` is `req_` + exactly 20 alphanumeric chars — `store.py:57`
- §2.2 (success envelope) — revise — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical factory clock — `envelope.py:27`, `store.py:60`
- §2.3 (pagination ordering) — revise — ambiguity — `created_at` ties broken by write order (earliest first), making ordering total and stable — `aggregates.py:11`, `store.py:163`
- §2.3 (filters) — insert — ambiguity — filters are exact-equality; empty-string filter treated as omitted; an id filter naming a nonexistent record matches nothing rather than erroring — `validators.py:212`
- §2.4 (record identity) — insert — ambiguity — `created_at`/`updated_at` stamped from host wall clock, not the logical clock — `store.py:141,154`
- §2.4 (logical clock) — revise — mismatch — startup default renders as `2026-08-01T00:00:00.000Z`; client datetimes accepted in any parseable ISO 8601 form (numeric offset or no zone -> UTC), normalised to UTC, stored/echoed at exactly 3 fractional digits (extra truncated), unparseable -> `ERR_VALIDATION_FAILED` — `store.py:81-116`, `validators.py:155`
- §2.5 (rounding) — insert — ambiguity — rounded quantities emitted as bare JSON numbers with no trailing zeros (`0.0`, not `0.00`); decimal places constrain the value, not printed width — `envelope.py:11-21`
- §2.7 rung 3 — insert — ambiguity — explicit `null` == omitted; undeclared extra fields ignored; integer-valued numbers like `5.0` accepted for integer fields, booleans never numeric; absent/blank body read as `{}` regardless of Content-Type, unparseable or non-object bodies -> `ERR_VALIDATION_FAILED` — `validators.py:19-98`
- §5 (catalogue preamble) — insert — ambiguity — unrouted paths and unsupported methods answer `ERR_NOT_FOUND` 404 with no auth check; unexpected failures answer `ERR_INTERNAL` 500, both in the standard error envelope (neither code is in the §5 table) — `app.py:36-53`
- §3.1 (model geometry) — revise — ambiguity — the four millimetre dimensions, both pixel counts and `modules_per_cabinet` must be whole numbers; only `cabinet_weight_kg` is an unrestricted positive decimal — `routes/catalogue.py:30-37`
- §3.2 (control-system headroom) — insert — ambiguity — a port capacity floored to 0 yields `effective_capacity_mbps` 0, no division and no percentage, and the project is refused with `ERR_DATA_LOAD_EXCEEDS_CAPACITY` — `calc.py:154`, `routes/projects.py:63`
- §3.3 (revision review) — insert — mismatch — the `REJECT` branch's `reason` requirement is evaluated after the state and segregation checks, so a reason-less `REJECT` on a non-`SUBMITTED` revision reports `ERR_INVALID_REVISION_STATE`; a `reason` sent with `APPROVE` is discarded — `routes/projects.py:169-182`

Already-pinned (no change): seven-role vocabulary and read-open-to-all, error->HTTP map exact for all 54 codes, version-starts-at-1/+1-per-mutation, `has_more`/`total_count` semantics, pagination defaults and bounds, all display-model/chamber/crew/project/revision field ranges and defaults (`module_dead_pixel_max` 3, `module_cluster_max` 1), region-code uppercase-letters-only, geometry validate-never-repair, `contract_amount_cents` per-cabinet-round-then-multiply order, `required_data_mbps` ceiling and port-capacity floor, the <=100.00% acceptance boundary, project-creation and revision-submission ladder orders, `revision_number` = count + 1, `required_load_kg_per_sqm` snapshot, APPROVE/REJECT write sets and `engineering_state` transitions.

### Pass 2 — calc, aggregates, routes/modules, routes/cabinets

**No `cp`** — 12 in-place `Edit` calls; pass 1's edits verified still present. **Delta:** 98,906 -> 100,906 chars (+2,000). **Counts:** 10 ambiguity-pins, 2 mismatch-revisions.

- §3.1 (derived model geometry) — revise — ambiguity — `required_load_kg_per_sqm` divides cabinet weight by `cabinet_area_sqm` *as already rounded to 4 dp*, not by the exact area — `calc.py:121-122`
- §3.4 (pixel testing) — insert — ambiguity — `dead_pixel_count`/`max_cluster_size` mandatory whole numbers >= 0; missing/fractional/negative -> `ERR_VALIDATION_FAILED` — `routes/modules.py:60-61`
- §3.4 (colour calibration) — insert — ambiguity — all three measurements mandatory; `measured_brightness_nits` a whole number >= 0; each coordinate strictly between 0 and 1 with at most 4 dp — `routes/modules.py:85-87`
- §3.4 (tolerance ladder) — insert — ambiguity — `REWORK -> CALIBRATED` is a legal direct transition (no fresh pixel test needed before an in-tolerance recalibration) — `routes/modules.py:91,112`
- §3.5 (cabinet planning) — revise — **mismatch** — PRD said any position "outside the grid" yields `ERR_CABINET_POSITION_TAKEN`; impl screens `grid_row`/`grid_col` < 1 at rung 3 as `ERR_VALIDATION_FAILED`, only past-the-far-edge reaches rung 42 — `routes/cabinets.py:22-23,28`
- §3.5 (installing a module) — revise — **mismatch** — PRD said `slot_index` must lie between 1 and `modules_per_cabinet` inclusive (`ERR_CABINET_SLOT_OCCUPIED`); impl rejects slot < 1 at rung 3 as `ERR_VALIDATION_FAILED` — `routes/cabinets.py:52,74`
- §3.5 (install transitions) — insert — ambiguity — both cabinet transitions evaluated on the same install, so a one-module-per-cabinet family goes `PLANNED -> POPULATED` in one install under a single version increment — `routes/cabinets.py:84-88`
- §3.5 (as-built uniformity) — insert — ambiguity — score is also null when the set's mean measured brightness is zero (no division attempted) — `calc.py:191-193`
- §3.6 (quarantine cascade hop 3) — insert — ambiguity — a project already `BLOCKED` is left alone by hops 3 and 4: no further version increment, no visit re-aborted — `aggregates.py:133-135`
- §3.7 (mounting) — insert — ambiguity — the project takes a version increment and fresh `updated_at` on *every* successful mount, even when `production_state` does not move — `routes/cabinets.py:182`
- §3.9 (`elapsed_warranty_months`) — insert — ambiguity — the seconds difference is clamped to zero when a wound-back clock puts `reported_at` before `warranty_start_at` — `calc.py:241-242`
- §3.9 (`PRO_RATA_REMAINING_TERM` credit) — insert — ambiguity — the remaining-term count is not floored at zero, so a case reported past the 60-month term yields a negative `credit_cents` — `calc.py:260-262`

Already-pinned: all `calc.py` constant tables and the `contract_amount_cents` / data-load / annual-fee / `spare_required_count` / `dead_pixel_ppm` / `chroma_error` / `color_bin_for` / `degradation_figures` / `cabinet_value_cents` formulas and rounding orders; `aggregates.by_created` ordering; all derived counters; `activate_contracts_for`; `contract_health`'s directional flips; install/remove/qa-approve/mount ladder orders, response bodies and status codes; both list endpoints' filter sets.

### Pass 3 — routes/burnin, routes/visits, routes/service

**No `cp`/Write** — in-place `Edit` only; passes 1-2's 25 changed lines all verified still present. **Delta:** 100,906 -> 106,020 chars (+5,114). **Counts:** 16 ambiguity-pins, 3 mismatch-revisions (19 PRD lines edited).

- §2.3 filters — revise — mismatch — pass 1 claimed *every* empty-string filter is ignored, but only id/code filters go through `query_str`; enum filters are vocabulary-screened, so `?run_state=` is `ERR_VALIDATION_FAILED` — `validators.py:203-216`, `service.py:435`, `burnin.py:178`
- §3.6 scheduling inputs — insert — ambiguity — `slots_required` has no upper bound (over-capacity is a rung-35 refusal, not rung 3); `ambient_c` accepts decimals — `burnin.py:25-27`
- §3.6 successful booking — insert — ambiguity — the six run fields that start null, and the chamber record's own version increment on schedule/complete/abort — `burnin.py:58-79,115-117,153-155`
- §3.6 completion inputs — insert — ambiguity — the three measurements' shapes; `measured_uniformity_pct` has no upper bound (a reading above 100 is stored) — `burnin.py:87-89`
- §3.6 failure cascade — insert — ambiguity — `baseline_module_ids` also stays empty on a failed run — `burnin.py:128-130`
- §3.6 abort — insert — ambiguity — `reason` is mandatory, min 1 char, no max length — `burnin.py:141`
- §3.7 visit booking — insert — ambiguity — the five visit fields that start null, plus the crew's version increment on booking and on release — `visits.py:59-72`
- §3.7 on-site calibration — insert — ambiguity — measurement shapes; the two project-relative floors are checked *after* ownership/state (brightness before uniformity); calibrate alone skips the `production_state` re-check — `visits.py:102-114`
- §3.8 named spare — insert — ambiguity — a named `module_id` is screened on `module_state` only; model-match and free-stock filters govern the auto-pick alone, so naming an already-reserved module re-points its reservation — `service.py:122-133`
- §3.8 spare release — insert — ambiguity — the project takes a version increment on the `AT_RISK` flip, and the contract's version increments on every reservation/release regardless of state movement — `service.py:137,161`, `aggregates.py:183-189`
- §3.9 case opening — insert — ambiguity — `symptom` is mandatory but may be the empty string — `service.py:176`
- §3.9 payload symmetry — insert — ambiguity — supplying the forbidden field is a rung-3 `ERR_VALIDATION_FAILED` ahead of all existence/state checks, unlike the later `ERR_MEASUREMENT_REQUIRED` — `service.py:178-183,208-211`
- §3.9 case creation — insert — ambiguity — `response_breached` starts false and the nine assessment/fulfilment fields start null — `service.py:227-238`
- §3.9 responding — insert — ambiguity — a breach increments the contract's version (and the project's on suspension); an on-time response leaves the contract untouched — `service.py:263-265`
- §3.9 assessing (intro) — insert — ambiguity — only `decision`/`assessment_basis` are rung-3 screened; branch-specific field demands run after the state and contract checks — `service.py:273-286`
- §3.9 assessing + credit paragraph — revise — mismatch — PRD called `assessment_basis` merely "optional", but approving a `BRIGHTNESS_DEGRADATION` case without it is `ERR_VALIDATION_FAILED`, evaluated after both the shortfall and replaceable-module refusals — `service.py:316-318`
- §3.9 resolved module — insert — ambiguity — a `MODULE_FAULT` approval stores a supplied basis verbatim, and the `ERR_NO_REPLACEABLE_MODULE` check applies to that type too — `service.py:311-334`
- §3.9 fulfilment selection — insert — ambiguity — a nominated replacement is screened only on reservation and colour bin; its `module_state`/model are not re-checked — `service.py:371-375`
- §3.9 fulfilment cascade — revise — mismatch — the version-increment list omitted the contract (incremented on every fulfilment) and the project (on the `AT_RISK` flip) — `service.py:412`, `aggregates.py:183-189`

**Orchestrator verification**: PRD_COMPLETED.md is 466 lines / 106,020 chars, carries all five `##` sections, and ends on the complete final catalogue row `| ERR_SPARE_PCT_BELOW_MINIMUM | 422 |` — intact, not truncated. `cmp` confirms it is NOT byte-identical to PRD_FINALIZED.md (82 diff lines / 41 changed pairs), so the scan genuinely ran. Also confirmed no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the green sweep (`find -newer results.1.json` empty), so the 8/8 x 184/184 result still describes the delivered artifacts. Stray `__pycache__` directories removed. Pipeline complete.

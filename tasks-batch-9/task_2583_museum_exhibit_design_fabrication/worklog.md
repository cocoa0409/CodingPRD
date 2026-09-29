# Worklog — task_2583_museum_exhibit_design_fabrication

## Step 1: Create task directory — 2026-09-03T15:11:38.423Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication` and its `workspace/` subdirectory. Index 2583 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-03T17:29:49.344Z

All three scaffold artifacts are complete and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication/SCAFFOLD.yaml` — 3555 lines / 188,621 B
- `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 4566 lines / 284,337 B
- `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication/SCAFFOLD_CORNER_DESIGN.yaml` — 8468 lines / 539,128 B

(`worklog.md` and `workspace/` in that directory are pre-existing, not part of this generation.)

## SCAFFOLD.yaml (§1.0–§1.7)

12 entities, 11 state machines, 9 calculations (all with dual variants where §1.7 demands), 59 validation rules (explicit priority ordering), 66 endpoints, 59 error codes, 6 roles (`ProjectManager`, `Curator`, `Conservator`, `FabricationLead`, `MuseumOperations`, `AccessibilitySpecialist`), `api_prefix: "/"`, `role_model: segregation_of_duties`, `consistency_model: immediate`. Top level is flat (`scenario … roles`); neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.

## §1.8 difficulty design

9 rules / 30 instances (all non-stub, each with a full `test_recipe`): `dual_variant_calc` (3), `combinatorial_formula` (3), `non_linear_state_machine` (4), `transitive_cascade` (3), `priority_pair_validation_conflict` (4), `boundary_precision_check` (4), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (3), `compensating_invariant` (3).

## §1.9 corner design

9 sections (the fixed taxonomy), 110 instances = **54 non-stub** + 56 `excluded_because` stubs:

| section | instances | non-stub |
|---|---|---|
| entities | 11 | 11 |
| state_machines | 14 | 9 |
| calculations | 18 | 5 |
| validations | 12 | 8 |
| endpoints | 15 | 9 |
| errors | 27 | 2 |
| rbac | 6 | 6 |
| cross_cutting_complexity_layers | 5 | 2 |
| consistency_model | 2 | 2 |

## Coverage audit

- **Lint**: `VERDICT: clean lint` — 2157 §1.8+§1.9 calls all conform to §1.5 (endpoint declared, role allowed, payload keys ⊆ input, capture JSONPaths resolve, OCC tokens all `${...}`), and every §1.1 FK has reverse-reachability in §1.5.
- **Endpoints**: 66 of 66 declared endpoints are exercised. The last four gaps were closed this pass with two new §1.9 `endpoints` instances — one `standard_crud` over the three filtered child listings (`GET /exhibit-projects/{id}/artifact-cases`, `.../interactives`, `GET /punch-items`, with the null-FK punch item as the trap) and one `cross_reference_link` over `GET /design-packages/{id}/superseded-packages` proving the supersede pointer names the immediate successor (A→B→C, one hop per link) rather than the newest package.
- **Errors**: all 59 codes are referenced; 25 are covered by §1.8 instances (stubbed with citations), the rest asserted in non-stub §1.9 recipes. Zero uncovered, zero stub-only-without-§1.8-backing.
- **Grounds**: every `grounds` token now resolves to a declared §1.1/§1.4/§1.5/§1.6 identifier. Fixed this pass: two stale underscored endpoint tokens in the §1.8 file (`DELETE_artifact_cases_id_placements_artifact_id`, `POST_shop_drawings_id_void` → `METHOD_/path` form) and two nonexistent `entities.<X>.constraints` tokens in §1.9 (→ `Artifact.fields.material_class`, `GalleryZone.fields.visitor_route_order`).
- **Stubs**: all 56 citations resolve to a real `<rule_id> / <instance name>` pair in the §1.8 file, and no stub carries a `test_recipe`.
- **Placeholders**: zero unresolved `${...}` references across all 54 non-stub recipes.
- Remaining minor slack (acceptable, not a lint error): validation priorities 1, 10–18, 24, 25, 30, 68, 76 are exercised by calls but not named in any `grounds` list; all 9 calculations and all 12 entities are cited.

_Orchestrator verification: `python3 -c "yaml.safe_load"` parses all three files; top-level keys confirmed (`SCAFFOLD.yaml` flat with 13 keys and neither design key present; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` → single key `scaffold_difficulty_design`; `SCAFFOLD_CORNER_DESIGN.yaml` → single key `scaffold_corner_design`)._

## Step 3: Copy shared files — 2026-09-03T17:30:21.697Z

Copied `./INSTRUCTION.md` → `tasks/task_2583_museum_exhibit_design_fabrication/workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-09-03T17:49:35.349Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication/workspace/PRD.md` — **469 lines, 103,374 bytes**. Ends at a genuine boundary (last row of the §5 error table).

**Top-level sections** (`grep -n '^## '`): `## 1. Introduction` (L3), `## 2. Global Specifications & System-Wide Principles` (L11), `## 3. Business Logic & Workflows` (L155), `## 4. Endpoint Definitions` (L331), `## 5. Error Code Catalogue` (L404). 20 subsections: §2.1–§2.11 (role table, verbatim §2.2 envelope, pagination, identity/logical clock, nested-path integrity, dual-path OCC, five-bucket ledger, rounding, posture brake, cascade discipline, 14-step rejection precedence) and §3.1–§3.9 (phase ladder; design packages/flow/accessibility/supersession; review rounds, quorum, veto, deadline sweep; zones/objects/environmental envelope; conservation rulings, zone slots, mount dimension; materials screening + four-link cascade; shop drawings + fabrication ledger; interactives durability/prototype/warranty; install calendar, punch list, closeout settlement).

**Scaffold coverage (machine-verified against SCAFFOLD.yaml):**
- Entities 12/12 (ExhibitProject, DesignPackage, ReviewRound, ReviewVote, GalleryZone, ArtifactCase, Artifact, Interactive, MaterialSpec, ShopDrawing, InstallWindow, PunchItem).
- State machines 11/11 including both ArtifactCase dimensions; 68/68 transitions and all 46 distinct state literals appear backticked in §1–§3.
- Calculations 9/9 including both two-variant families (`schematic_estimate`/`shop_drawing_actual`, `spec_stage`/`prototype_verified`); every numeric constant in `calculations[]` appears in the prose (automated constant-presence diff: 0 missing).
- Validations 59/59, all with priority, reflected in the §2.11 ladder plus per-workflow prose; every one of the 59 error IDs is referenced in §1–§4 prose, not only in the §5 table.
- Endpoints 66/66 — §4 table method+path set is an exact bijection with the scaffold, no duplicates, all rows exactly 4 columns; 201 for the 13 creates, 200 elsewhere (verified against each endpoint's `code`).
- Errors 59/59 in a 2-column table with scaffold HTTP statuses (incl. the outliers 402 `ERR_FABRICATION_BUDGET_EXCEEDED`, 412 stale-version pair).
- Roles 6/6, all opaque identities.

**Contract 1 — Field-Name Coverage**
- `entities[].fields`: 155 required, 155 present, 0 missing
- `endpoints[].request_body`: 93 required, 93 present, 0 missing
- `endpoints[].query_params`: 22 required, 22 present, 0 missing
- `endpoints[].path_params`: 2 required (`id`, `artifact_id`), 2 present, 0 missing
- Status: PASS (164 unique identifiers)

**Contract 2 — Rule Coverage**
- `validations[]` with priority: 59/59 covered, ordering stated in §2.11 and re-stated at each decision point (fiscal last, closure capacity after per-zone conflict)
- `concurrency_rules[]` OCC rejections: 2/2 (`expected_project_version` → `ERR_STALE_PROJECT_VERSION`, `expected_case_version` → `ERR_STALE_CASE_VERSION`)
- `state_machines[].transitions`: 68/68
- `calculations[]`: 9/9, both dual-variant families with per-line-item rounding, the capped wear penalty, the two opposing interval geometries, and the pinned 7-step closeout waterfall
- `validations[]` conditions: all documented with their triggering operation and error
- `endpoints[].side_effects` / `applies_to`: cross-entity effects covered (four-link material cascade, drawing-void reversal + case/mount/object revert, window-complete `RESERVED → PLACED` sweep, closeout punch closure and bucket rebalance); every multi-endpoint `applies_to` scope stated as a scope
- `entities[].fields[]` structured content: `conditions`, `panel_roles`, `objective_codes`, denial/waiver/void reason fields all described field-by-field
- sibling-branch symmetry: `APPROVE` vs `APPROVE_AS_NOTED` (identical money, different conservation gate), `APPROVE` vs `REJECT` on prototypes (verified index written vs deliberately untouched), placement removal `PLACED → DEINSTALLED` (keeps `assigned_case_id`) vs `RESERVED → UNPLACED` (clears it)
- Status: PASS

**Contract 3 — Path Purity (§3 only)**
- backtick tokens scanned: 1,074 (334 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

**Leakage:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` nor `worklog.md` was opened, grepped, or referenced, and no other `task_*/` directory was read. No worked-example figures or `test_recipe` assert values appear; every number in the PRD traces to `SCAFFOLD.yaml` constants, bands or bounds. Two documented scaffold-internal reconciliations carried through: the header is `X-User-Role` (skill convention over the scaffold's `X-Role`), and `ERR_DUPLICATE_VOTE` covers duplicate `voter_role` and duplicate `voter_user_id` alike.

_Orchestrator truncation check (per the known doc-generator failure mode): `tail -6` ends on the final `| ERR_NOTHING_TO_SETTLE | 409 |` row of the §5 table — a real section boundary, not a mid-sentence cut. Independent cross-check: all 59 scaffold error codes and all 66 scaffold endpoint paths appear in PRD.md; zero occurrences of `scaffold_difficulty`, `scaffold_corner`, `test_recipe`, or the difficulty instruction string. No regeneration needed._

## Step 5: Generate unit tests — 2026-09-03T19:08:07.558Z

The test suite for `task_2583_museum_exhibit_design_fabrication` is complete at the task root. Nothing was written into `workspace/` (confirmed: no `workspace/test_helpers`, no `workspace/test_suite`; only `INSTRUCTION.md`, `PRD.md`, and the concurrent agent's `implementation/` are there), and `workspace/implementation/` and `worklog.md` were never read.

## Files delivered

`test_helpers/` — 1,965 lines: `__init__.py` 118, `api_client.py` 374, `api_errors.py` 151, `assertions.py` 171, `constants.py` 128, `factories.py` 266, `fixtures.py` 431, `test_users.py` 85, `types.py` 241.

`test_suite/` — 12,537 lines: `conftest.py` 20; `test_01_shop_cost_and_durability_variants.py` 422/7 tests, `test_02_cost_formula_and_settlement_composition.py` 510/8, `test_03_two_dimensional_state_machines.py` 565/12, `test_04_conservation_and_review_cascades.py` 607/10, `test_05_validation_precedence_ladder.py` 763/12, `test_06_inclusive_boundaries_and_deadlines.py` 878/17, `test_07_cross_entity_gating.py` 560/11, `test_08_install_calendar_geometry.py` 367/9, `test_09_compensating_ledger_invariants.py` 732/12, `test_10_entity_field_and_geometry_edges.py` 449/8, `test_11_entity_envelope_and_slot_edges.py` 624/10, `test_12_phase_and_review_state_machine_edges.py` 724/9, `test_13_case_and_mount_state_machine_edges.py` 602/10, `test_14_calculation_edges.py` 720/13, `test_15_validation_edges_environment_and_access.py` 632/9, `test_16_validation_edges_materials_and_windows.py` 633/8, `test_17_endpoint_contract_edges.py` 530/5, `test_18_endpoint_listing_and_settlement_edges.py` 608/4, `test_19_error_catalogue_and_authorization_edges.py` 994/8, `test_20_layered_complexity_and_consistency.py` 597/4.

## Counts and verification

- 186 test functions, 202 collected cases (parametrize expansion). `pytest test_suite/ --collect-only -q` → 202 collected, 0 errors; every file `py_compile`-clean; `import test_helpers` succeeds.
- Queue A (difficulty): 98 tests from **30/30** instances (index has zero stubs), >=2 tests each. Queue B (corner): 88 tests from **54/54** non-stub instances; none of the 56 stubs translated.
- I ran an independent AST audit (`/tmp/audit_2583.py`): every test has a docstring whose **last** line is its single `Design:` tag; zero untagged, zero dual-tagged, zero dangling — all 84 instance names resolve to a verbatim `- name:` line in the correct section/rule_id of the source yaml; every quoted docstring sentence (>=40 chars) is a verbatim substring of `PRD.md`. Final result: **0 problems**. Leakage grep for "scaffold" / "design index" / "corner case" / section markers outside the tag lines: clean.

## Skipped or dropped under the PRD-first filter

No instance was skipped wholly; the following sub-assertions were dropped because the PRD does not uniquely derive them. Error ids not derivable: `ERR_INVALID_MOUNT_STATE` for the uncleared-drawing mount coupling; `ERR_OFFGASSING_LIMIT_EXCEEDED` for a plain APPROVE on a CONDITIONAL_SAFE spec; the COMMISSIONING-advance block; the wrong-status prototype ruling; 7 terminal-state probes on a WARRANTY_CLOSED project (the phase gate outranks resource state, so the index's `ERR_INVALID_*_STATE` codes are ambiguous); the two unphase-gated window triggers. Field values not derivable: `verified_by_user_id` on a waived punch item (the inherited index contradiction — asserted as neither null nor `pm-01` in both instances; status `WAIVED`, `waiver_reason` and `verified_at` are asserted); review-round `version` after a non-resolving vote; `panel_roles` array ordering; the absence of a vote update/delete route. One unreachable half-instance dropped (re-submission after a conservation freeze is blocked by the freeze itself), and two placements the index expects to succeed were re-asserted as the refusals the PRD mandates (`ERR_ENV_ENVELOPE_INFEASIBLE`, `ERR_SECURITY_TIER_INSUFFICIENT`).

Where the index contradicted the PRD, the PRD won and the number was recomputed: shop-drawing **actual** total 142500 (labour multiplier 1.00), not the index's 166250 estimate; `revise_count == 2` after two REVISE votes; zone slots 0/capacity before a conservator ruling; `open_revision_count` 0 / posture OPEN after merely opening a round; settlement buckets start at 0, not null; `revision` as integer; `phase` not `current_phase`; illegal single-code `objective_codes` and 2-seat panels replaced with legal ones; `CERAMIC` and `CONSERVATION_REVIEW` replaced with declared enum values.

One helper defect found and fixed: `fixtures.project_in_phase` ran the interactive's prototype/fabrication bench work after the project had left FABRICATION, so the CLOSEOUT and WARRANTY_CLOSED targets were unreachable. Split into `prepare_interactive` (SPECIFIED->FABRICATED, invoked while still in FABRICATION) and `commission_interactive` (FABRICATED->COMMISSIONED at COMMISSIONING); no test file referenced the old function, and the suite still collects at 202.

## Step 6: Generate implementation — 2026-09-03T19:08:07.558Z

Implementation is complete, compiling, and smoke-verified.

## Files — `/home/ubuntu/github/CodingPRD/tasks/task_2583_museum_exhibit_design_fabrication/workspace/implementation/`

| file | lines | role |
|---|---|---|
`start.sh` | 10 | guarded launcher: installs flask only if missing, `exec python3 app.py`
`requirements.txt` | 1 | `flask==3.0.3`
`app.py` | 75 | `create_app()`, blueprint registration, 3 error handlers, `0.0.0.0:$PORT`
`store.py` | 73 | in-memory `db` (12 dicts), logical clock, `new_row`
`errors.py` | 134 | `ApiError` + HTTP status map for all 59 error IDs
`envelope.py` | 116 | meta/response_type/data envelope, pagination, filters
`auth.py` | 94 | `@endpoint(roles=...)`, role gate before path resolution, SoD helper
`validate.py` | 164 | field validators, ISO-8601 parsing, `OBJ-` pattern
`calc.py` | 374 | the 9 calculations + every tariff constant
`helpers.py` | 268 | phase/mount ladders, 404 lookups, derive-at-read counters, `touch`
`serializers.py` | 305 | the 12 entity serializers
`cascades.py` | 138 | the shared cascade chains
`routes_projects.py` | 207 | project CRUD, advance-phase, review-sweep, closeout
`routes_packages.py` | 256 | packages, supersession, rounds, votes
`routes_zones.py` | 92 | gallery zones + slot views
`routes_artifacts.py` | 76 | collection objects
`routes_cases.py` | 277 | cases, placements, conservation ruling, mount-advance
`routes_interactives.py` | 185 | specs, prototypes, fabrication, commissioning
`routes_materials.py` | 165 | material specs, screening, conservator ruling
`routes_drawings.py` | 227 | shop drawings, review, decision, void
`routes_windows.py` | 214 | install windows: buffers, both interval geometries
`routes_punch.py` | 146 | punch items, verify, waive
`routes_clock.py` | 23 | the one unauthenticated endpoint

3,620 lines total. No `__pycache__`, no data file, no seeding — `Store.reset()` runs at import, so a `start.sh` re-invocation wipes every byte.

## Endpoint coverage: 66/66
Enumerated from `app.url_map` — 66 method/path pairs, matching the PRD §4 table one-for-one including `DELETE /artifact-cases/{id}/placements/{artifact_id}`.

## The 9 calculations
All in `calc.py`, all on `Decimal` with `ROUND_HALF_UP` at named points only: `fabrication_cost` (three line items each rounded to whole cents *before* summing, with `_schematic` 1.15/1.20 and `_actual` 1.00/supplied-waste wrappers over one shared core), `durability_index` (one function, `_spec` = 0 credit / `_verified` = +8 credit) plus `maintenance_tier` bands, `case_envelope` (strictest floor/ceiling/lux wins, plus security rank), `package_flow` (0.65 m²/visitor-hour, capped at 100.00), `material_verdict` (three ordered branches, limits keyed by assembly), `window_buffers`/`effective_bounds`/`windows_conflict` (half-open, buffered), `closure_capacity_peak` (closed interval, unbuffered, all starts before all ends at equal timestamps, `created_at` tie-break), `posture_from_counters` (first match wins), `closeout_settlement` (the pinned 7-step waterfall, final release by exact integer subtraction).

## The 11 state machines
Ladder-driven machines use explicit successor maps in `helpers.py` (`PHASE_SUCCESSOR`, `MOUNT_SUCCESSOR`). Everything else is an explicit status set test per endpoint, ordered by the §2.11 precedence ladder. The two parallel dimensions on `ArtifactCase` (`status` vs `mount_status`) are coupled only where the PRD couples them. Cascades that more than one machine shares live in `cascades.py`, including the depth-4 chain `material_rejection_cascade -> void_drawing -> money release -> revert_case_to_draft -> release_reserved_objects` + zone-slot release, and the cyclic review path `package_to_revision_requested -> revert_phase_for_revision -> deny_requested_windows`. `touch()` is idempotent per request via `g.touched`, so a row mutated twice in one request advances `version` by exactly 1.

## Smoke test — passed, server killed by port
Ran `PORT=28377 bash start.sh`, booted in <12 s, then walked a full lifecycle: project -> zone -> object -> interactive -> material -> SCHEMATIC -> case -> placement -> conservation approval -> package -> round -> 2-of-3 quorum -> DESIGN_DEV -> 4-seat panel (quorum 3) -> FABRICATION -> drawing -> review -> approval -> window request/approval. Hand-checked figures all matched: `case_volume_m3` 0.3 / `silica_gel_kg` 2.1; estimate 667000+306000+22950 = 995950; actual 609000+280500+21038 (21037.5 rounded half up) = 910538 committed, `uncommitted_cents` 49089462; DUST_GENERATING buffers 30/120 with `effective_end_at` 19:00. Negative paths verified: 401 unauthenticated, 403 wrong role, 400 `limit=999`, 404 `ERR_PROJECT_NOT_FOUND`, 412 `ERR_STALE_CASE_VERSION`, 422 `ERR_ACCESSIBILITY_REQUIREMENTS_UNMET`. Killed via `lsof -tiTCP:28377` (pid 4161673) plus the recorded wrapper pid; port confirmed free. No pattern kill was used.

Two fixes made after the last checkpoint: the commissioning warranty term is now written back only after every precondition passes (a refused commissioning leaves the row untouched), the spurious `touch(case)` in window completion is gone, and five missing §3.1 child-creation phase gates were added at ladder step 10 (zones/objects/interactives -> the three planning phases; cases -> `SCHEMATIC|DESIGN_DEV`; materials -> planning + `FABRICATION`; drawing `start-review` -> `DESIGN_DEV|FABRICATION`).

_Orchestrator layout verification: `test_helpers/` (9 files) and `test_suite/` (21 files) are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, and `implementation/` (23 files). No stray `workspace/test_helpers` or `workspace/test_suite`._

## Step 7: Run tests and iterate — 2026-09-03T19:42:51.810Z

All 8 parallel rounds are green: **202/202 passed, 0 failed, 0 errors** in every round (`workspace/implementation/results.1.json` … `results.8.json`, ~381s each).

## Summary

**Iterations run: 3 full 8-round `setsid nohup` sweeps.**
- Iteration 1: 8/8 rounds at 199/202, identical 3-test failing set (deterministic, not load-induced).
- Iteration 2 (after 3 implementation fixes): 8/8 rounds at 201/202, one remaining failure.
- Iteration 3 (after the test split): 8/8 rounds at 202/202.

### Tests deleted
None outright. One STEP 1c split — `test_suite/test_05_validation_precedence_ladder.py`:
- `test_once_the_freeze_lifts_the_identical_ruling_reports_the_budget` → renamed to `test_with_no_conservation_block_in_the_way_the_ruling_reports_the_budget`. The **unreachable-precondition half** was dropped: the test rejected a case (which per §3.5 "Every object in it whose `placement_status` is `RESERVED` returns to `UNPLACED` … `placed_artifact_count` therefore falls to 0") and then resubmitted it, but §3.5 also states "submission requires `placed_artifact_count` of at least 1 … `ERR_CASE_HAS_NO_ARTIFACTS`", and §2.9 lists "reserving an object into a case" among the ten frozen-blocked operations — pinned independently by the passing `test_03::test_the_freeze_outranks_the_mount_rule_even_on_a_fresh_case_version`, which requires re-placement into that same rejected case to answer `ERR_PROJECT_FROZEN_CONSERVATION`. So no PRD-faithful implementation can reach a successful `REJECTED → CONSERVATOR_REVIEW` rework of a case whose only object was `RESERVED`. Making it pass would have required stripping the PRD-required emptiness check, which is forbidden. The **PRD-covered half was kept verbatim**: `ERR_FABRICATION_BUDGET_EXCEEDED` / 402 on the 27,000,000-cent ruling against 9,000,000 uncommitted cents, plus the sheet-unchanged and ledger-unchanged assertions (this is the suite's only coverage of that error, so it was preserved rather than deleted).

### Fixes applied to `test_helpers/`
None — `fixtures.py`, `factories.py`, `test_users.py` and `assertions.py` were all traced and found PRD-faithful.

### Fixes applied to `workspace/implementation/`
1. `helpers.py` — `project_counters` / `project_posture` / `require_not_frozen` gained optional `exclude_case_id` / `exclude_material_id`. §3.5: the rework path "is only reachable once every *other* conservation block on the project has already been cleared", so a row's own rejection must not bar its own resubmission. Defaults are `None`, so serialized posture and the other nine frozen-blocked operations are untouched.
2. `routes_cases.py::submit_case` — passes `exclude_case_id=case["id"]` to the freeze check (§3.5).
3. `routes_materials.py::submit_material` — passes `exclude_material_id=material["id"]`; §3.6 "Resubmitting from `REJECTED` clears that rejection's contribution to `conservation_block_count`" would otherwise be unreachable.
4. `cascades.py::void_drawing` — new `revert_case=True` parameter gating the subject-case revert; the §3.6 link-three material-rejection cascade keeps the default.
5. `routes_drawings.py::void` — passes `revert_case=drawing["status"] in ("APPROVED","APPROVED_AS_NOTED")`, per §3.7 "Voiding a sheet still in `SUBMITTED` or `UNDER_REVIEW` moves no money and reverts no case."
6. `routes_drawings.py::decide_drawing` — reordered to ladder §2.11: segregation (step 3, only when the row is on file) → body shape (step 4) → existence 404 (step 5). Previously `ERR_DRAWING_NOT_FOUND` preempted `ERR_INVALID_REQUEST`.
7. `routes_packages.py::create_round` — same reorder: body shape (`panel_roles`, `decision_deadline_at`) now validated before `ERR_PACKAGE_NOT_FOUND`.

Storage remains in-memory dicts only; no endpoints, fields, side effects or seeded data were added. Diagnostic scratch artifacts (`mini_suite/`, scratch server on port 18583) were removed/killed by path and pid — no pattern kills used.

_Orchestrator verification (per the known "clean sweep with no artifacts" failure mode): all 8 `results.*.json` exist (~62.8 KB each, mtimes 19:42:49–19:42:51) and each independently parses to `passed=202, total=202, failed=0, errors=0`. No `mini_suite/` scratch dir remains; `__pycache__` removed by the orchestrator. Step 7 applied 7 `implementation/` fixes, so Step 8 is NOT skipped._

## Step 8: Finalize PRD — 2026-09-03T19:48:44.345Z

Done. `PRD_FINALIZED.md` created as a two-line patch of `PRD.md`.

## Counts
- `PRD.md`: 469 lines / 103,374 bytes
- `PRD_FINALIZED.md`: 469 lines / 104,082 bytes — **0.0% line delta** (+708 bytes, 2 lines revised)
- Headings identical (`diff` of all `^#` lines is empty); both files end at the same `## 5. Error Code Catalogue` row `| ERR_NOTHING_TO_SETTLE | 409 |`.

## Changes
- **§3.6 (line 253) — revise** — the "the project must not be frozen" precondition on `POST /material-specs/{id}/submit-for-conservation` now states that this freeze test disregards the material's *own* `REJECTED` contribution to `conservation_block_count` (mirroring §3.5's case rework), while any other outstanding block still refuses it — `routes_materials.py:111` (`require_not_frozen(project, exclude_material_id=material["id"])`), `helpers.py:198-232, 258-263`.
- **§3.7 (line 285) — revise** — "Voiding a sheet still in `SUBMITTED` or `UNDER_REVIEW` moves no money and reverts no case" scoped to **this endpoint**, with an explicit note that the case-revert suppression does not carry into §3.6's link-three material-rejection cascade, which reverts the subject case of every sheet it voids regardless of the status voided out of — `routes_drawings.py:233-235` (`revert_case=drawing["status"] in ("APPROVED","APPROVED_AS_NOTED")`) vs `cascades.py:98,126` (cascade keeps `revert_case=True`).

## Per-edit pre-edit search log

**Edit 1 — §3.6 material freeze exclusion**
- (a) Subject: the frozen-posture gate and `conservation_block_count` exclusion semantics.
- (b) Enumerated (grep `require_not_frozen|require_posture_open|project_posture|project_counters|conservation_block_count`): `helpers.py:198/234/258/265` (definitions, defaults `None`); exclusion-passing callsites only `routes_cases.py:183` (submit_case) and `routes_materials.py:111` (submit_material); non-excluding callsites `routes_drawings.py:65,185`, `routes_windows.py:45,109`, `routes_packages.py:40,121`, `routes_cases.py:115,253`, `routes_interactives.py:97,122,143`, `routes_projects.py:93,95,177`; serialized posture `serializers.py:18-33` and posture list filter `routes_projects.py:65` / counters `routes_projects.py:139` (all unexcluded); `calc.py:326` ordering.
- (c) Adjustment: added the clause "unlike the other frozen-blocked operations of §2.9, which count every block" so the exclusion is not read as a global change to posture; verified all ten §2.9 operations plus serialized/filtered posture use the unexcluded form, and that the exclusion is a no-op unless the row's own status is `REJECTED` (so the wording holds for the `APPROVED`/`CONDITIONAL` re-review path too). Kept §3.5's existing "every *other* conservation block" sentence verbatim — it already pins `routes_cases.py:183`.

**Edit 2 — §3.7 void vs. cascade case revert**
- (a) Subject: whether a sheet's status at void time suppresses the subject-case revert.
- (b) Enumerated (grep `void_drawing|revert_case_to_draft|release_reserved_objects|material_rejection_cascade`): `cascades.py:98-118` (`void_drawing`, `revert_case=True` default, money release keyed off `actual_cost_cents`), `cascades.py:121-126` (cascade, default kept), `cascades.py:83-95` (`revert_case_to_draft`: slot, `conditions`, `MOUNT_FABRICATED→MOUNT_DESIGN`), `cascades.py:74-81` (`release_reserved_objects`, also called from `routes_cases.py:233` on `REJECT`), sole void endpoint `routes_drawings.py:225-236`. No other void path exists.
- (c) Adjustment: limited the contrast to the *case revert* only and left "moves no money" unqualified, because money movement is governed identically in both paths by `actual_cost_cents` being non-null (a `SUBMITTED`/`UNDER_REVIEW` sheet always has it null); also referenced "its case revert" rather than restating the rule, so §3.6 link three's own `APPROVED`/`CONDITIONALLY_APPROVED` case-status precondition is not accidentally dropped.

**Items deliberately left unpatched** (PRD already uniquely determines them; impl was fixed toward the PRD, so no silence to pin): diff items 1-2 (§3.5 already says the rework path opens once every *other* block is cleared), items 4-5's money half, and items 6-7 (the reorders restore §2.11's stated step 4 → step 5 ordering, body shape before the 404). The split test's dropped half is an inherent consequence of §3.5 + §2.9 (re-placing into a rejected case is frozen-blocked with no exclusion, `routes_cases.py:115`), not a PRD gap.

_Orchestrator verification: `wc -l -c` confirms 469 lines both files (103,374 B → 104,082 B); `diff` reports exactly 4 changed lines (2 revised lines, before/after); `tail` confirms PRD_FINALIZED.md ends on the same final error-table row as PRD.md — no truncation._

## Step 9: Complete PRD — 2026-09-03T20:15:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (single-pass scans are known to silently no-op on an implementation this large; each pass edited the same `workspace/PRD_COMPLETED.md` in place). Partition: pass A = `app.py store.py auth.py envelope.py errors.py validate.py helpers.py serializers.py routes_clock.py`; pass B = `calc.py cascades.py routes_drawings.py routes_materials.py routes_interactives.py routes_punch.py`; pass C = `routes_projects.py routes_packages.py routes_cases.py routes_zones.py routes_artifacts.py routes_windows.py`.

### Pass A (global/cross-cutting) — 469/104,082 → 470/110,834 (+1 line, +6,752 chars); 13 ambiguity-pins, 5 mismatch-revisions
- §1 — insert — ambiguity — trailing slash accepted as equivalent (`app.py:44` `strict_slashes = False`).
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars (`envelope.py:12,21-22`).
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not wall time (`envelope.py:37-41`).
- §2.2 — insert — ambiguity — enumerated the read-time-derived fields (project counters/posture/`uncommitted_cents`, zone slot split, case count + envelope limits + flags, `maintenance_tier`) (`serializers.py:18,42,111,132,202`).
- §2.2 — insert (new bullet) — ambiguity — unmatched route → 404, unaccepted method → 405, server fault → 500, all in the error envelope with `ERR_INVALID_REQUEST`; §5 statuses govern application-level rejections only (`app.py:53-66`).
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` malformed, whitespace ignored, omitted/empty takes default, `offset` unbounded (empty page, `has_more` false), both validated after the path 404 (`envelope.py:78-97`).
- §2.3 — insert — ambiguity — filters are exact case-sensitive equality, unknown value matches nothing, empty ≡ absent; `requires_gallery_closure` accepts true/false/1/0/yes/no any case (`envelope.py:100-116`).
- §2.3 — revise — mismatch — "Four collections deviate" → two: zones are NOT ordered by `visitor_route_order` and windows NOT by `starts_at`; both default to `created_at` ascending (`routes_zones.py:57,65,88,96`, `routes_windows.py:81`, `helpers.py:127-128,152-153`).
- §2.3 — insert — ambiguity — shared-`created_at` ties break on creation order; descending project list reverses the tie-break too (`store.py:71-73`, `routes_projects.py:67`).
- §2.4 — insert — ambiguity — instants keep sub-millisecond precision for comparison but render truncated to 3 digits (`envelope.py:25-34`).
- §2.4 — insert — ambiguity — every declared field always present; `null` never omitted (all 12 serializers).
- §2.4 — insert — ambiguity — clock endpoint requires no headers, may move backwards, `data` is `{"current_utc": …}`; global ISO-8601 rule (Z/z or offset normalised, no-offset read as UTC) (`routes_clock.py:16-23`, `auth.py:61-77`, `validate.py:110-124`).
- §2.7 — insert — ambiguity — `reserved_case_slots` is the read-time count of the zone's `APPROVED`/`CONDITIONALLY_APPROVED` cases; available = capacity − that (`helpers.py:189-195`).
- §2.8 — insert — ambiguity — figures are JSON numbers not strings; money integer cents, rounded quantities decimal numbers (`serializers.py:11-14`, `calc.py:100-106`).
- §2.9 — revise — mismatch — counters are not stored on the project row: only `conservation_veto_count` is; the other five recompute from live rows per serialize/gate (`helpers.py:198-231`).
- §2.10 — insert — ambiguity — a row touched twice in one request still advances `version` by exactly one (`helpers.py:40-57`).
- §2.11 step 4 — insert — ambiguity — optional field sent as `null` ≡ omitted; strict types; body malformed only when a required field exists; undeclared fields ignored; `Content-Type` never inspected (`validate.py:17-42,69-107`).
- §2.11 step 5 — revise — mismatch — real interleave pinned: path rows resolve before body shape-check, SoD on the resolved row ahead of step 4, body-supplied ids resolve after step 4 (`routes_drawings.py:168-176` vs `routes_cases.py:26,100-104` et al).
- §4 intro / rows — insert+revise — ambiguity/mismatch — clock excepted from header requirement; placement and vote are 201 creation endpoints; gallery-zone row dropped the nonexistent "security tier"; clock row role list → "Any caller, with or without headers".
- Cross-check: §5 error table matches `errors.py::ERROR_HTTP` exactly (59 rows, no status differences); every serializer key appears in PRD prose and no PRD-named resource field is missing from the serializers.

### Pass B (calculations, money, cascades, fabrication/materials/interactives/punch) — 470/110,834 → 470/113,395; 11 ambiguity-pins, 7 mismatch-revisions
- §2.9 — revise — mismatch — the frozen-blocked list said "ten" and omitted five impl actually blocks; now fifteen (adding opening a review round, submitting a case for conservation, submitting an interactive prototype, marking an interactive fabricated, submitting a material for conservation) and notes the two resubmissions are the only block-discounting ones — verified against all 15 `require_not_frozen`/`require_posture_open` call sites.
- §2.11 step 13 — revise — mismatch — blocking punch items checked **above** warranty term (`routes_interactives.py:170-180`).
- §2.3 — revise — mismatch (pass A wording) — filter equality is against the value the resource reports, derived fields included; the `maintenance_tier` filter compares a computed value (`routes_interactives.py:76`).
- §3.1 — revise — mismatch — "Shop drawings may be issued **and decided** only in `FABRICATION`" was false: `decide_drawing` has no `require_phase` (`routes_drawings.py:180-188`).
- §3.5 / §3.6 link four / §3.7 void — revise ×3 — mismatch — the shared object release moves only `RESERVED` objects in ascending `created_at`; an already-`PLACED` object stays, so `placed_artifact_count` falls to the number still `PLACED` (not "to 0") and envelope limits null out only then (`cascades.py:74-94`).
- §3.3 — insert — ambiguity — a resolving vote touches package and project (both versions +1); a non-resolving vote touches the round alone (`cascades.py:37-52`).
- §3.6 ruling — insert — ambiguity — `APPROVE`/`APPROVE_WITH_CONDITIONS` touches only the material row, unlike `REJECT` (`routes_materials.py:161-167`).
- §3.7 decision / §3.8 prototype ruling — insert ×2 — ambiguity — `note` is validated as an unbounded string then discarded, appearing in no response (`routes_drawings.py:175`, `routes_interactives.py:119`).
- §3.7 void — insert — ambiguity — `void_reason` required and non-blank (`routes_drawings.py:229`).
- §3.8 commission — insert ×2 — ambiguity — the supplied term is written back only after every precondition passes (a refused commissioning leaves `warranty_months`/`status`/`updated_at`/`version` untouched); body `warranty_months` bounded 0–120 as at specification (`routes_interactives.py:157,167,182`).
- §3.8 specification — insert — ambiguity — an `objective_code` outside the project's array is `ERR_INVALID_REQUEST`, judged with body shape ahead of uniqueness and phase (`routes_interactives.py:35-37`).
- §3.9 punch — insert ×2 — ambiguity — `verification_note` and `waiver_reason` each required and non-blank (`routes_punch.py:112,133`).
- §4 — insert — ambiguity — `/material-specs/{id}/shop-drawings` filterable by `status` (`routes_materials.py:98`).
- Pass A's flagged items resolved: both `note` silences closed; `material["verdict"]` confirmed written at exactly two points (`routes_materials.py:59,120`), the resubmit recompute always a no-op since no input field has an update path — §3.6 reads consistently, no edit needed.

### Pass C (projects, packages/reviews, zones, objects, cases, windows) — 470/113,395 → 470/114,883; 8 ambiguity-pins, 5 mismatch-revisions
- §3.1 (L170) — revise — mismatch — windows may be *requested* only in `FABRICATION`/`INSTALLATION`; the ruling carries no phase gate (freeze + window status only), nor do complete/cancel (`routes_windows.py:100-148,170-214`). This was the item pass B handed over.
- §2.11 step 5 — revise — mismatch — **two** operations reverse the path rule, not one: the drawing ruling and opening a review round (malformed body on unknown package ⇒ `ERR_INVALID_REQUEST`) (`routes_packages.py:104-107`).
- §2.11 step 12 — revise — mismatch — mount dimension is tested before case status; the successor test fires ahead of the conservation-status coupling (`routes_cases.py:255-263`).
- §3.5 (L230) — revise — mismatch — the conservator's case ruling touches the owning project row too, in every branch (`routes_cases.py:237`).
- §4 placements-list row — revise — mismatch — objects still assigned in **any** placement status (DEINSTALLED included), aligning the table with §3.4 (`routes_cases.py:145`).
- §3.1 — insert ×2 — ambiguity — a failed per-step admission test answers `ERR_INVALID_PROJECT_PHASE` unless the step names another identifier; objective coverage reads the `objective_code` field alone regardless of case/interactive status (`routes_projects.py:98-145`).
- §3.3 — insert — ambiguity — the sweep increments the project's version unconditionally (even with nothing lapsed) and answers with the updated project, not the lapsed rounds (`routes_projects.py:159-164`, `cascades.py:144`).
- §3.4 — insert ×2 — ambiguity — object list also accepts a `condition_status` filter; placement removal responds with the updated object (`routes_artifacts.py:65`, `routes_cases.py:172`).
- §3.5 — insert ×2 — ambiguity — submit-for-conservation writes the case row only, project version does not move; the missing-cleared-drawing refusal for `MOUNT_FABRICATED` is `ERR_INVALID_MOUNT_STATE` (`routes_cases.py:193-195,264-269`).
- §3.9 — insert — ambiguity — closeout body bounds: both URLs non-blank 1–500 chars, `parts_commitment_years` integer ≥ 0 with no ceiling (`routes_projects.py:172-174`).
- Pass C corrected two pass-A universal claims (review-round body ordering; mount-vs-case check order) as flat factual errors about its own modules; nothing else from A/B was reverted. §3.5's corrected `placed_artifact_count` wording left untouched.
- Both pass-B "unobservable" calls confirmed with no PRD change: closeout step one's truthiness filter cannot differ (an APPROVED/APPROVED_AS_NOTED sheet always carries a non-null `actual_cost_cents`, and zero contributes zero either way); `closure_capacity_peak`'s `_seq` tie-break cannot move the peak (permuting equal-timestamp same-type events leaves the prefix sums identical).
- Final consistency read: §2.9's fifteen-operation list matches the fifteen freeze call sites exactly; §2.11's ladder matches every gate order; the §4 table matches every route, method and role list. No residual ambiguity or mismatch known after three passes.

### Totals
- `PRD.md` 469 lines / 103,374 B → `PRD_FINALIZED.md` 469 / 104,082 B → `PRD_COMPLETED.md` **470 lines / 114,883 B** (+1 line, +10,801 chars over PRD_FINALIZED; 32 ambiguity-pins, 17 mismatch-revisions across the three passes).

_Orchestrator verification: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the known "scan never ran" failure mode) — `diff` reports 87 changed lines. File still ends on the `| ERR_NOTHING_TO_SETTLE | 409 |` row, so no truncation. `find -newermt 19:43` confirms no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the green sweep at 19:42:51, so the verified 8/8 × 202/202 result still describes the delivered code. Pipeline complete._

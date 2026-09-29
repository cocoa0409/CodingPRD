# Worklog — task_2200_transformer_switchgear_manufacturing

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2200_transformer_switchgear_manufacturing/` and `tasks/task_2200_transformer_switchgear_manufacturing/workspace/`.

## Step 0 (resume audit): — 2026-08-31T00:00:00.000Z

Resume-mode audit of task directory: only `worklog.md` and an empty `workspace/` existed. No SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, PRD_FINALIZED.md, or PRD_COMPLETED.md. Pipeline resumes at Step 2.

## Step 3: Copy shared files — 2026-08-31T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2200_transformer_switchgear_manufacturing/workspace/INSTRUCTION.md` (53 lines). Run out of order (ahead of Step 2) since it has no dependency on the scaffold.

## Step 0 (resume audit #2): — 2026-08-31T00:00:00.000Z

Second resume-mode audit. On-disk state: `worklog.md`, `workspace/INSTRUCTION.md` (53 lines, byte-identical to project-root `INSTRUCTION.md`). Nothing else present — no SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, PRD_FINALIZED.md, PRD_COMPLETED.md. Steps 1 and 3 confirmed valid; pipeline resumes at Step 2 (scaffold generation).

## Step 0 (resume audit #3): — 2026-08-31T00:00:00.000Z

Third resume-mode audit. `find . -type f` returns exactly two files: `worklog.md` (17 lines) and `workspace/INSTRUCTION.md` (53 lines, `diff -q` against project-root `INSTRUCTION.md` → identical). All other pipeline artifacts absent. Steps 1 and 3 valid and NOT redone; pipeline resumes at Step 2 (scaffold generation) and continues through Step 9.

## Step 0 (resume audit #4): — 2026-08-31T19:57:15.610Z

Fourth resume-mode audit. `find . -type f` → exactly two files: `worklog.md` (21 lines) and `workspace/INSTRUCTION.md` (53 lines; `diff -q` vs project-root `INSTRUCTION.md` → identical, non-truncated). Absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Verdict: Step 1 valid, Step 3 valid — neither redone. Pipeline resumes at Step 2 (scaffold generation) and runs through Step 9.

## Step 0 (resume audit #5): — 2026-08-31T20:05:00.000Z

Fifth resume-mode audit. `find . -type f` → exactly two files: `worklog.md` (25 lines) and `workspace/INSTRUCTION.md` (53 lines; `diff -q` vs project-root `INSTRUCTION.md` → IDENTICAL, non-truncated). Still absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Verdict: Step 1 valid, Step 3 valid — neither redone. Pipeline resumes at Step 2 (scaffold generation) and runs through Step 9.

## Step 0 (resume audit #6): — 2026-08-31T20:30:00.000Z

Sixth resume-mode audit. `find . -type f` → exactly two files: `worklog.md` and `workspace/INSTRUCTION.md` (53 lines; `diff -q` vs project-root `INSTRUCTION.md` → IDENTICAL, non-truncated). Still absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Verdict: Step 1 valid, Step 3 valid — neither redone. Step 2 has never produced output across five prior crashed runs. Launching Step 2 (scaffold generation) now, then continuing through Step 9.

## Step 0 (resume audit #7): — 2026-08-31T20:45:00.000Z

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — COMPLETE — 2026-08-31T21:20:00.000Z

Attempt #10 (fresh continuation agent, digest + 120-line append cap) succeeded. **SCAFFOLD.yaml = 5010 lines** (was 2829).

Subagent summary, verbatim:

> Done. All four sections appended and cross-checked.
>
> `SCAFFOLD.yaml` — **5010 lines** (was 2829), parses cleanly.
>
> Top-level keys now: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.
>
> ### Counts
> | Section | Key | Count |
> |---|---|---|
> | §1.4 Validation rules | `validations:` | **82** (priorities 1..82, strictly ordered) |
> | §1.5 Endpoints | `endpoints:` | **127** (unique ids, unique method+path) |
> | §1.6 Error catalog | `errors:` | **82** |
> | §1.7 RBAC matrix | `roles:` | **13** |
>
> Validation ladder bands: 1-6 auth/authz (incl. 4 segregation-of-duties pairs), 7-26 existence, 27-31 payload/pagination, 32-33 OCC, 34-41 state, 42-53 safety/compliance, 54-66 constraint, 67-74 temporal, 75-82 capacity/fiscal.
>
> ### Cross-reference checks (all passed programmatically)
> - **error_id xref**: referenced set == defined set exactly — 0 undefined, 0 unreferenced.
> - **Concurrency rules**: all 5 `write_endpoint` values resolve to declared endpoints; both `ERR_STALE_ORDER_VERSION` (412) and `ERR_STALE_COMPONENT_VERSION` (412) are defined.
> - **Transition-event coverage**: every `POST`/`GET`/etc. path mentioned anywhere in §1.0-§1.3 (61 action paths) exists in `endpoints:`. `system:` cascades were deliberately given no endpoints.
> - **RBAC coverage**: 0 endpoints without `roles:`; 0 role names used that are absent from the matrix; 0 matrix roles unused. Every role has a valid `identity:` — `CustomerWitness` is `entity_backed:WitnessParty`, the other 12 are `opaque`.
> - **Token integrity**: every field/entity/status token in the new sections is drawn from the digest (a scripted scan for field-shaped tokens found no invented names); all 16 calculation names referenced exist and all 16 are referenced.
> - **FK reverse-reachability**: every `FK ->` field in §1.1 has either a sub-resource `GET .../<child-segment>` or a filtered-list `GET /<child-collection>` with that FK as an input, all returning `<Child>[]`.
>
> ### Notes for downstream
> - Added `POST /_clock/set_current_utc` (PlantAdmin only) with the mandatory fixed startup default **`2026-08-01T00:00:00Z`** stated in its `description:` — required because the scaffold's calculations reference a logical clock throughout.
> - Added a few business (not seed) endpoints for state reachability: `POST /suppliers/{id}/receipt-events`, `POST /long-lead-components/{id}/receipts`, `POST /engineered-orders/{id}/escalation-clauses`, `POST /commodity-index-points`, `POST /test-bays`, `POST /witness-parties`, `POST /factory-acceptance-tests/{id}/test-reports`, plus computed reads (`/posture`, `/financial-summary`, `/quality-summary`, `/schedule`, `/load`).
> - One YAML gotcha hit and fixed: PyYAML rejects a bare `field?` token inside a flow sequence, so all 48 `input:` lists had their optional entries quoted (`"limit?"`).

Orchestrator independently verified: `yaml.safe_load` parses; 20 entities / 17 state_machines / 5 concurrency_rules / 16 calculations / 82 validations / 127 endpoints / 82 errors / 13 roles; endpoint ids unique; method+path unique; validation priorities 1-82 all unique; neither design key present.

## Steps 2b + 2c: Difficulty (§1.8) and Corner (§1.9) designs — LAUNCHED CONCURRENTLY — 2026-08-31T21:22:00.000Z

Both launched in a single assistant message (true concurrency). Each reads only its own ~105-line SKILL.md slice — 2b gets offset=562 limit=110 (§1.8) and is forbidden §1.9; 2c gets offset=671 limit=104 (§1.9 + Quality Checklist) and is forbidden §1.8 — plus the two digests. Same 120-line append cap.

Generated a second scratch digest for them: `API_DIGEST.txt` (396 lines) — all 127 endpoints as `id | METHOD path | roles`, all 82 validations as `priority | category | error_id | http | applies_to` + check text, all 82 error ids with http status, all 13 roles with identity. Together with VOCAB_DIGEST.txt this lets both design agents target the §1.5 endpoint table exactly without loading the 5010-line scaffold (which is what killed the earlier agents). Both digests are scratch — DELETE both before the task is complete; they are not part of the expected output tree.

Both agents were explicitly told: `test_recipe` may reference only endpoints/error_ids present in API_DIGEST; `system:` transitions are internal cascades with NO endpoint and must be driven via the endpoint whose side effect triggers them; instance `name:` values must be unique because the unit-test generator copies them verbatim into `Design: Difficulty/<rule_id>/<name>` and `Design: Corner/<section>/<name>` docstring tags. `scaffold_lint.py` deferred until both files land.

## Step 6: Generate implementation — COMPLETE — 2026-09-01T00:20:00.000Z

**workspace/implementation/ = 23 files, 5029 lines**, every module passes `py_compile`.

Subagent summary, verbatim:

> Implementation complete and verified.
>
> ## Files
> | file | lines | role |
> |---|---|---|
> | `start.sh` | 9 | reads `$PORT`, conditional pip install, `exec python3 app.py` (foreground, binds `0.0.0.0`) |
> | `requirements.txt` | 1 | `Flask>=2.0` |
> | `app.py` | 72 | app factory, 11 blueprints, ApiError/404/405/500 handlers |
> | `clock.py` | 99 | logical clock, default `2026-08-01T00:00:00Z` |
> | `errors.py` | 122 | all 82 error ids → HTTP status + per-family `NOT_FOUND` map |
> | `envelope.py` | 79 | meta/response_type/data envelope, `req_`+20 alnum, pagination |
> | `store.py` | 108 | in-memory dicts, version/`_seq`, `public()` strips `_` keys |
> | `validation.py` | 131 | 4 ordered payload passes + OCC helpers |
> | `rbac.py` | 223 | 127-key role table, 6-step auth order |
> | `posture.py` | 152 | derived `production_posture` + reason codes, money rollup |
> | `common.py` | 261 | existence/state/terminal gates, filters, cascade helpers |
> | `calc.py` | 508 | the 16 calculations with pinned rounding modes |
> | `routes_orders.py` | 269 | clock + orders |
> | `routes_drawings.py` | 234 | submittal drawings |
> | `routes_escalation.py` | 333 | clauses, index points, adjustments |
> | `routes_suppliers.py` | 255 | suppliers + long-lead components |
> | `routes_allocations.py` | 183 | component allocations |
> | `routes_tests.py` | 338 | test bays + FATs |
> | `routes_witness.py` | 294 | witness parties + assignments |
> | `routes_reports.py` | 313 | test reports + compliance labels |
> | `routes_shipment.py` | 335 | shipment releases + site storage |
> | `routes_commissioning.py` | 343 | commissioning jobs + punch items |
> | `routes_warranty.py` | 367 | warranty claims + failure analysis reports |
>
> 5029 lines total; every module passes `py_compile`.
>
> ## Ladder enforcement
> Each handler calls the same fixed sequence of shared gates, so the 82 rungs are an ordered pipeline rather than scattered checks: `rbac.authenticate()` (1–6: headers → role recognition incl. entity-backed `CustomerWitness` → endpoint permission → SalesEngineer ownership → SoD → witness identity) → `common.resolve()` per path/body FK (7–26) → `validation.body()` + `validation.validate()` whose four passes run required → type → enum → range, then `envelope.pagination()` (27–31) → `validation.check_order_version` / `check_component_version` (32–33) → `common.check_state` / `check_order_not_cancelled` / `check_order_fulfillment` / `check_design_released` / `check_engineering_open` / `check_fat_administrable` (34–41) → safety/compliance gates (42–53: arc energy, label stale/not-issued, report issued/incomplete, bay kV/impulse/availability, credentials, blocking punch, quarantine, suspension) → constraint gates (54–66: uniqueness, revision rounds, bay window conflict, witness assignment/blackout, retest predecessor, stage share/final/sequence) → temporal gates (67–74, all clock-derived) → capacity/quota/fiscal gates (75–82).
>
> ## Logical clock
> `clock.py` holds a single module-level instant, reset to `2026-08-01T00:00:00Z` in `create_app()`; `POST /_clock/set_current_utc` (PlantAdmin) is the only mutator. Every timestamp (`created_at`, `updated_at`, `issued_at`, `cleared_at`, `shipped_at`, `energized_at`, `published_at`, envelope `api_request_timestamp`) and every time-dependent calculation (warranty anchor/expiry with end-of-month clamping, storage billable days, escalation index usability, bay windows, witness day buckets, mobilization gate) reads `clock.now()`. No `datetime.utcnow()` anywhere outside `clock.py`.
>
> ## Storage
> Pure Python dicts in `store.py`, wiped by `store.reset()` at import and in `create_app()`. No SQLite/JSON/tmp writes; the only startup constant is the clock instant. Confirmed on a fresh boot: `total_count=0` for all 14 top-level list families.
>
> ## Verification performed
> - **Route parity:** all 127 registered Flask rules match `rbac.ENDPOINT_ROLES` exactly (0 missing, 0 extra), and cross-checked against `SCAFFOLD.yaml`: 0 path/method mismatches, 0 role-list mismatches, 0 success-status mismatches (201 for creations incl. the two scaffold-declared 201 receipt endpoints, 200 elsewhere).
> - **Errors:** all 82 catalogue ids present with exactly the scaffold's HTTP statuses.
> - **Smoke (boot from `start.sh`, `PORT` honoured):** `GET /engineered-orders` → 200; `POST /engineered-orders` → 201; read-back → 200; error paths return proper envelopes (`ERR_ORDER_NOT_FOUND` 404, `ERR_INVALID_PAGINATION` 400, `ERR_UNKNOWN_ROLE` 401 for an unresolvable CustomerWitness, `ERR_ROLE_NOT_PERMITTED` 403, `ERR_DUPLICATE_CODE` 409, `ERR_CONSEQUENTIAL_NOT_COVERED` 422).
> - **Full pipeline drive (~65 calls, all green):** order → drawing submit/review/APPROVED (engineering `DESIGN_RELEASED`, `released_drawing_revision=1`) → escalation clause → supplier/component/allocation/commit (fulfillment auto-advances to `MATERIAL_ALLOCATED`) → start-production → bay + FAT schedule → witness invite/confirm → start → report issue (verdict `PASS`) → label generate (`energy=19.8`, `ppe=3`, `boundary=1848mm`, rating text) → verify → issue → FAT conclude PASS → provisional escalation adjustment (raw 2,000,000, months `['2026-06','2026-09']`, accepted → net 52,000,000) → shipment release → clear → stage → site storage (15 billable days, fee 55,200) → ship → deliver → commissioning mobilize/energize → punch assign/resolve/close → job `COMPLETE` + startup certificate, order auto-`CLOSED` with posture `RESTRICTED`/`["ORDER_FULFILLED"]` → warranty claim → RMA (cap 12,500,000) → receive-unit → failure analysis publish (claim `WARRANTABLE`, credit 890,000, waterfall `{PARTS 400000, LABOR 240000, FREIGHT 250000, CONSEQUENTIAL 0}`, component `QUARANTINED`, supplier indices 95.83) → settle, with stages rebilled so `billed_to_date == net_contract_value == 51,110,000`. All servers shut down afterwards; no lingering processes, no files written by the server.
>
> Two notes for you: (1) I fixed a real rounding bug found in `calc.arc_flash_values` — the arc-flash boundary now ceils to the next whole millimetre instead of being floored after a 2-dp ceil. (2) `test_suite/` and `test_helpers/` appeared in the task directory during this session (from the concurrent test-generation agent); per your instruction I did not read them, so the implementation remains strictly spec-derived.

**Isolation contract held.** The impl agent confirms it did not read `test_suite/`/`test_helpers/` even though the concurrent Step 5 agent created them mid-session. This is the property the single-message concurrent launch buys.

Orchestrator independently verified:
- `python3 -m py_compile *.py` over all 22 modules → **ALL COMPILE OK**.
- `start.sh` reads `$PORT`, `cd`s to its own dir, `exec python3 app.py` in the FOREGROUND. Notable good detail: the pip install is *conditional* on `import flask` failing, with an inline comment that an unconditional install would cause boot-time contention under per-test-server reboots — correct concern for a harness that relaunches before every test.
- Disk-persistence smell scan (`sqlite|open(...,'w'|json.dump|pickle|shelve|/tmp/`) → **no matches**. In-memory only, as required.
- Wall-clock leakage scan (`utcnow|datetime.now|time.time()`) outside `clock.py` → **none**. All time flows through the logical clock.
- Fresh boot on PORT=8791: `ss -ltn` confirms **`LISTEN 0.0.0.0:8791`** (not localhost-only). Queried all 14 top-level list families → **`total_count=0` on every one**, independently confirming the zero-seeded-entities rule.

## Step 4: Generate PRD — COMPLETE — 2026-08-31T23:30:00.000Z

**workspace/PRD.md = 599 lines.**

Subagent summary, verbatim:

> The PRD is complete.
>
> `workspace/PRD.md` — **599 lines**
>
> ## Section outline
> - `# Transformer & Switchgear Manufacturing API — Product Requirements Document`
> - **§1. Introduction** (3 paragraphs, domain framing)
> - **§2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control (13 roles, 6 ordered auth checks, entity-backed `CustomerWitness`, 4 segregated pairs) · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Common Resource Properties and the Two Persistence Tiers · 2.5 Nested Path Resolution (20 not-found codes) · 2.6 The Two Order Dimensions and the Derived Production Posture (5 FROZEN_CLASS / 8 RESTRICTED_CLASS reason codes, class dominance) · 2.7 Optimistic Concurrency Control (5 rules) · 2.8 Precision, Rounding and Basis Points (3 documented departures from round-half-up) · 2.9 Conservation Invariants (money, component units, bay hours) · 2.10 The Logical Clock (`2026-08-01T00:00:00Z`) · 2.11 The Validation Priority Ladder (all 82 rungs in 9 bands)
> - **§3. Business Logic & Workflows** — 9 domain-derived subsections: 3.1 order booking/commercial header · 3.2 submittal drawings and the revision cycle (4-hop BOM cascade) · 3.3 commodity escalation (PROVISIONAL/FINAL variants, negotiation cycle) · 3.4 long-lead components, allocation and preemption (victim selector, release-penalty tiers, quarantine) · 3.5 factory acceptance testing, bay scheduling and witness administration (half-open bay windows vs. UTC-day witness blackout sets) · 3.6 test reports and the arc-flash compliance label (ceiling rounding, PPE tiers, `ERR_ARC_ENERGY_UNLABELABLE`, STALE/VOID revert paths) · 3.7 staged shipment, site storage and delivery (floor-plus-remainder billing waterfall, six-step storage fee with pinned discount tier) · 3.8 field commissioning and punch list closure (compound aggregate completion) · 3.9 warranty claims, failure analysis and supplier quality (window expiry with end-of-month clamping, cap min-then-max order, 4-bucket credit waterfall, 6-hop publish cascade, TRAILING vs LIFETIME index)
> - **§4. Endpoint Definitions** — 1 intro paragraph + 4-column table, **127 rows**, all paths absolute with nothing prepended (multi-root, 21 resource families + the clock family)
> - **§5. Error Code Catalogue** — 2-column table, **82 rows**
>
> ## Hard Contract reports
> - **Contract 1 — Field-Name Coverage: PASS.** Pass A: all 193 entity field names (including the four common fields) appear in the PRD; 0 missing. Pass B: all 131 distinct endpoint input field names appear; 0 missing. Supplementary pass: all 118 enum values declared in entity constraints appear; 0 missing.
> - **Contract 2 — Rule Coverage: PASS.** 100 state-machine transitions across 17 machines (including both independent `EngineeredOrder` dimensions and the derived posture), 5 concurrency rules, 16 calculations, all 82 validation rungs, 127 endpoints (all paths present verbatim), 82 error codes (all present verbatim), 13 roles (all present verbatim).
> - **Contract 3 — §3 Path Purity: PASS.** Programmatic scan of §3 (81,916 characters) found zero `/`-prefixed path tokens and zero bare HTTP-method tokens (`GET`/`POST`/`PATCH`/`PUT`/`DELETE`); every operation in §3 is expressed as role + action + state transition.
>
> ## Confirmation
> I did **not** open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` at any point, and I read no sibling task under `/home/ubuntu/github/CodingPRD/tasks/`. All content derives from `SCAFFOLD.yaml`, the skill spec, and the fixed §2.2 block.
>
> ## Two scaffold inconsistencies resolved in favour of `state_machines`
> 1. `disposition_submittal_drawing` side-effects claim `engineering_status := ENG_OPEN` on `REVISE_AND_RESUBMIT`, but the state machine declares an explicit `SUBMITTAL_IN_REVIEW` self-loop; the PRD documents the self-loop.
> 2. `start_factory_acceptance_test` describes `BAY_SCHEDULED or WITNESS_CONFIRMED -> IN_PROGRESS` and sets `mobilization_at := logical clock` on mobilize, while the state machine allows start only from `WITNESS_CONFIRMED` and treats `mobilization_at` as an input precondition; the PRD follows the state machine (harmless in practice, since `witness_required: false` auto-advances a test into `WITNESS_CONFIRMED`).

Orchestrator independently verified: 599 lines; section headings §1-§5 as described; **127** endpoint table rows matching `^\| *(GET|POST|PATCH|PUT|DELETE) `; **82** distinct `ERR_*` tokens. Re-ran the §3 path-purity scan independently over the extracted §3 slice (81,913 chars) — **0** path-like `/resource` tokens, **0** bare HTTP-method tokens. Also ran an independent anti-leakage scan: extracted all **98** instance `name:` values from the two design files and grepped PRD.md for each — **0 leaked**. The withholding contract held.

Noted for later: the doc-generator adjudicated two internal scaffold inconsistencies in favour of `state_machines` over endpoint `side_effects`. Since PRD is the implementer's only contract and Step 6 reads PRD, the implementation will follow the state-machine reading; this is the correct precedence and is recorded here in case a Step 7 failure traces back to either site.

## Steps 5 + 6: Unit tests and implementation — LAUNCHED CONCURRENTLY — 2026-08-31T23:35:00.000Z

Both launched in a single assistant message per the skill's concurrency requirement. Beyond throughput this gives physical isolation: Step 6's impl agent cannot read `test_suite/` because the directory does not exist at its spawn time (verified — task tree held only SCAFFOLD*.yaml, worklog.md, workspace/INSTRUCTION.md, workspace/PRD.md at launch).

Step 5 (tests) reads SCAFFOLD + BOTH design indices + PRD; told the queue inventory (21 queue-A, 77 queue-B), the mandatory `Design: Difficulty/<rule_id>/<name>` / `Design: Corner/<section>/<name>` docstring tags, and the PRD-first two-condition skip filter (skip, never weaken/xfail). Step 6 (impl) reads INSTRUCTION + SCAFFOLD + PRD only.

Both prompts carry: bounded-range reading (never one Read over the 5010-line scaffold), the multi-root `api_prefix: ""` warning against re-prefixing paths, the logical-clock contract (`POST /_clock/set_current_utc`, fixed default `2026-08-01T00:00:00Z`, all time-dependent math reads it not wall-clock), and the write-early/many-small-files protocol with `py_compile` after each module. Step 6 additionally carries the in-memory-only + zero-seeded-entities rule, ordered-82-rung-ladder requirement, `start.sh` foreground/$PORT/0.0.0.0 contract, and a mandatory boot+POST+read-back smoke check before exit.

## Step 2 COMPLETE — lint clean, exit 0 — 2026-08-31T23:05:00.000Z

Fix subagent cleared all 14 remaining violations. Independently re-verified by the orchestrator: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` with **real exit code 0** (checked separately from the pipe, not via `${PIPESTATUS}` on a `tail`).

Subagent summary, verbatim:

> **`VERDICT: clean lint ...` — `EXIT=0`** (was 14 violations).
>
> ### Edits made
> **SCAFFOLD.yaml**
> 1. L3724 `create_long_lead_component` — `allocation_policy` → `"allocation_policy?"` (quoted). Cleared violations [11] and [1-of-c].
>
> **SCAFFOLD_DIFFICULTY_DESIGN.yaml**
> 2. `warranty_waterfall_...` setup[30] — added `mobilization_at: "2026-02-10T08:00:00Z"` (clock is `2026-02-10T09:00:00Z` at the immediately-following `mobilize`, whose §1.3 precondition is `logical clock >= job.mobilization_at`).
> 3. `warranty_waterfall_...` setup[40] (WC-X) — added `suspect_component_id: "${comp_id}"` (captured at setup[7]).
> 4. `warranty_waterfall_...` setup[45] (WC-Y) — same `suspect_component_id: "${comp_id}"`.
> 5. `warranty_waterfall_...` setup[43] (FAR-X) — added `attributed_supplier_id: "${sup_id}"` (captured at setup[6]).
> 6. `warranty_waterfall_...` setup[48] (FAR-Y) — same `attributed_supplier_id: "${sup_id}"`.
> 7. `far_publish_six_hop_...` setup[30] — added `mobilization_at: "2026-02-10T08:00:00Z"` (same timeline shape).
> 8. `allocation_create_four_rung_ladder_...` trigger[0] — `expected_component_version: 9999` → `"${comp_v0} + 1"`, reusing the existing `comp_v0: $.data.version` capture at setup[3].
> 9. `allocation_create_four_rung_ladder_...` trigger[1] — same change; keeps `ERR_STALE_COMPONENT_VERSION` polarity (§1.6 defines it as "does not equal the current version", so `+1` is a genuine mismatch, and unlike `- 1` it can't hit version 0).
> 10. `fat_schedule_reads_three_foreign_test_bay_fields_...` setup[6] `POST /suppliers` — `as: MaterialsPlanner` → `as: PlantAdmin`.
> 11. `fat_schedule_...` setup[11] `POST .../start-production` — `as: PlantAdmin` → `as: MaterialsPlanner`. §1.5 untouched.
>
> **SCAFFOLD_CORNER_DESIGN.yaml** — used the capture route for both #12/#13; no new rule (d) violations (lint exempts `error_id`/`message` from JSONPath resolvability via `_ERROR_ENVELOPE_FIELDS`).
> 12. Renamed `create_engineered_order_ignores_client_supplied_system_fields` → `create_engineered_order_extra_field_input_ignored`; payload and asserts untouched.
> 13. `unrecognised_role_header_returns_unknown_role` trigger — added `captures: { err_id: "$.data.error_id" }`; `as: Machinist` kept.
> 14. `customer_witness_may_read_one_order_but_not_list_all_orders` denied `GET /engineered-orders` — added `captures: { err_id: "$.data.error_id" }`; `as: CustomerWitness` kept.
>
> ### Verification
> - All three files parse via `yaml.safe_load`. SCAFFOLD.yaml has **no** `scaffold_difficulty_design`/`scaffold_corner_design` key; each design file still has exactly its one top-level key.
> - Name uniqueness holds: difficulty **21/21 unique**, corner **77/77 unique**, no collisions from the rename.
> - Line counts: SCAFFOLD 5010 (unchanged), difficulty 3440 (unchanged), corner 3071 (+2, the two added `captures:` lines). No structural churn.
>
> ### One deviation you should know about (flagging, not asking)
> Edits #5/#6 needed a companion change to stay executable. Those two FAR payloads had `root_cause_code: "WORKMANSHIP"`, and SCAFFOLD.yaml L2173 makes it a **publish precondition** that `attributed_supplier_id is null` when `root_cause_code != SUPPLIER_DEFECT` — while §1.5 L4497 makes `attributed_supplier_id` a *required* input. Those two clauses are mutually unsatisfiable, so a WORKMANSHIP report can never legally publish under this scaffold; adding the supplier id alone would have made the subsequent `POST /failure-analysis-reports/${far_x}/publish` fail its own precondition. I therefore also flipped `root_cause_code` to `SUPPLIER_DEFECT` in those two payloads (matching all six other FAR payloads in the file, which are uniformly `SUPPLIER_DEFECT`). Outcome polarity is preserved: L2101/L4535 route **both** `SUPPLIER_DEFECT` and `WORKMANSHIP` to `WARRANTABLE`, so the credit waterfall still runs; `quarantine_recommended: false` keeps cascade hops 2-4 dormant; and the instance's 14 asserts reference only claim buckets, credits and order totals, none of which touch root cause or supplier quality. A possible supplier PROBATION flip (hop 6) is unasserted here and gates nothing later in the recipe.
>
> Also touched: the `setup_narrative` line in `allocation_create_four_rung_ladder_...` said `comp_v0` "is reused verbatim by every rung", which edits #8/#9 falsified — reworded to note the two stale rungs send `${comp_v0} + 1`. Prose only.

### Orchestrator follow-up: fixed the ROOT contradiction the fix agent only worked around

The agent's flagged deviation was a real find but its remedy was local (change 2 payloads). The underlying scaffold defect was still present and would have poisoned Steps 5-7. Verified directly:
- §1.1 `FailureAnalysisReport.attributed_supplier_id` description: *"FK -> Supplier.id; supplier the root cause is attributed to, **null for workmanship or misapplication**"*.
- §1.2 publish preconditions L2172-2173: `when root_cause_code == SUPPLIER_DEFECT, attributed_supplier_id is not null` / `when root_cause_code != SUPPLIER_DEFECT, attributed_supplier_id is null`.
- §1.5 `create_failure_analysis_report` input listed `attributed_supplier_id` as REQUIRED.
- `root_cause_code` domain is 5-valued: `SUPPLIER_DEFECT | WORKMANSHIP | MISAPPLICATION | TRANSPORT_DAMAGE | UNDETERMINED`.

Consequence: for **4 of the 5** root causes a FAR could be created but could never publish, making the entire `NON_WARRANTABLE` cascade arm (L2109, triggered by `MISAPPLICATION`/`TRANSPORT_DAMAGE`/`UNDETERMINED`) unreachable dead code, along with the WORKMANSHIP path into `WARRANTABLE` (L2101). Tests generated against those branches in Step 5 would have been unpassable by any PRD-faithful implementation.

Fix applied to §1.5: `attributed_supplier_id` → `"attributed_supplier_id?"` (quoted per the flow-sequence gotcha). The entity's own description makes required-ness definitively the bug. Re-linted: still **clean, exit 0** — the agent's worry that optionalising it would re-trip the required-field rule was unfounded (rule (c) fires on omission of a REQUIRED field; optional fields may be present or absent). Left the agent's `SUPPLIER_DEFECT` payload change in place: it is valid, lint-clean, and its 14 asserts hold either way.

### Scratch cleanup
Deleted `VOCAB_DIGEST.txt`, `API_DIGEST.txt`, `SCAFFOLD.yaml.prefixbak`. Task tree now contains exactly the four spec'd Step-1-3 artifacts: SCAFFOLD.yaml (5010), SCAFFOLD_DIFFICULTY_DESIGN.yaml (3440), SCAFFOLD_CORNER_DESIGN.yaml (3071), worklog.md, workspace/INSTRUCTION.md.

## Step 4: Generate PRD — LAUNCHED — 2026-08-31T23:10:00.000Z

Subagent reads doc-generator SKILL.md + SCAFFOLD.yaml ONLY. Both design files explicitly withheld (§1.8 depth / §1.9 breadth are test-targeting indices; their worked-example numbers and `test_recipe` asserts must not leak into the prose the implementer reads). Told to read the 5010-line scaffold in bounded ranges rather than one call, given approximate section offsets, and warned that `api_prefix: ""` is deliberate — paths are already absolute across 21 resource families and must not be re-prefixed or described as single-root. Same write-early / ≤120-line-append protocol that finally beat the crash loop.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — COMPLETE — 2026-08-31T22:40:00.000Z

Subagent summary, verbatim:

> `SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete.
>
> **Final state: 3440 lines, 9 rules, 21 unique instances (all non-stub depth probes, queue A; 0 stubs).**
>
> | rule_id | instances |
> |---|---|
> | dual_variant_calc | 2 |
> | combinatorial_formula | 3 |
> | non_linear_state_machine | 2 |
> | transitive_cascade | 2 |
> | priority_pair_validation_conflict | 3 |
> | boundary_precision_check | 3 |
> | cross_entity_state_dependency | 2 |
> | resource_temporal_overlap | 2 |
> | compensating_invariant | 2 |
>
> Instances added in this final segment:
> - **cross_entity_state_dependency**: (a) FAT schedule re-reading three foreign `TestBay` columns — `max_kv 144` → P47, `supports_impulse false` → P48, `status MAINTENANCE` → P49 — then succeeding on the *same* bay after a `PATCH` touching only `status`, with `rated_kv 145 == max_kv 145` admitted; (b) warranty-claim creatability decided two levels away — identical payload returns `ERR_WARRANTY_WINDOW_UNAVAILABLE` three times, then 201 the moment the last `PunchListItem` closes and the job flips `PUNCH_OPEN -> COMPLETE`; plus the 18-month expiry clamp `2026-08-31T12:00Z → 2028-02-29T12:00Z` (leap-year clamp) with equality = `ERR_WARRANTY_WINDOW_EXPIRED`.
> - **resource_temporal_overlap**: (a) `bay_occupation_window` half-open edges with the changeover buffer *inside* the window (16:59 → conflict, 17:00 → accepted, mirror edge `window_end == existing.window_start` accepted, `scheduled_hours_total` 6→14→8→14 across abandon); (b) `witness_daily_load` UTC day-bucket capacity (a 22:00 test crossing midnight counts only against its start day) vs. the `{day-1, day+1}` travel-blackout day set, exercised in both directions (candidate-side and confirmed-side) plus `ERR_WITNESS_DAY_CAPACITY` at the strictly-less boundary.
> - **compensating_invariant**: (a) component-unit conservation `S = on_hand + consumed` held at 10/10/12/12/12/12/12 across reserve, commit, receipt, preempt, release and FAT-PASS consume, with `on_hand == available + reserved + committed` pinned at all seven observations; (b) FAR retract as a *partial* compensation — indices restored bit-exactly (91.25/82.50 → 100.00/100.00 on differing TRAILING/LIFETIME denominators 8 vs 4), quarantine guarded while a second PUBLISHED report survives, but the hop-3 `RELEASED` allocation never restored so order C ends `RESTRICTED[MATERIAL_INCOMPLETE]`, not `OPEN`.
>
> Verification (`/tmp/verify2.py`): parses cleanly; top-level keys exactly `['scaffold_difficulty_design']`; 21/21 names unique; **0 unknown endpoint paths** (758 `call:` entries all matched against API_DIGEST after `${var}` normalization); **0 unknown error_ids**; **0 unbound `${var}`** in payloads, path templates or asserts; every `as:` role valid; every instance has `grounds`, `distinguishing_aspect`, `setup`, `setup_api_calls`, `trigger`, `assert`. All `grounds` refs resolve (`calculations.*` names, `validations[priority=N]` within 1..82, `concurrency_rules[...]` kebab id); I normalized the newer `state_machines.X.transitions[A->B]` refs to the file's dominant `state_machines.X.A->B` form and fixed one `concurrency_rules.` → `concurrency_rules[...]` ref. `scaffold_lint.py` was not run, per instruction.

Orchestrator independently verified: 3440 lines; top keys exactly `['scaffold_difficulty_design']`; 9 rules; 21 instances, 21 unique names.

## Step 2 lint gate: `scaffold_lint.py` — 41 violations found, root-caused, 27 cleared by 1-token fix — 2026-08-31T22:50:00.000Z

First joint lint run over all three files: **VERDICT: 41 violation(s)**, exit 1. Coverage line confirms the linter saw everything: 127 §1.5 endpoints, 20 §1.1 entities, 21 §1.8 instances, 77 §1.9 instances, **1113 calls scanned**.

Histogram: 27 × `(f) FK_REVERSE_UNREACHABLE`, 7 × `(c) required input field missing from payload`, 4 × `(b) role not allowed by §1.5`, 2 × `(e) expected_*_version must be a ${var}, not a literal`, 1 × `(c) payload key not declared in §1.5 input`.

### Root cause of all 27 FK violations: a bad `api_prefix` (NOT 27 real gaps)

Both 2a's self-check and a manual read of §1.5 said reverse-reachability was fine — e.g. `list_component_allocations GET /component-allocations` declares `engineered_order_id?`, `long_lead_component_id?`, `preempted_for_allocation_id?` and returns `ComponentAllocation[]`, which is textbook filtered-list form. Read `lint_fk_reverse_reachability` (scaffold_lint.py:706-760) to find why it disagreed: the check computes `child_list_path = f"{prefix}/{child_seg}"` from `api_prefix`. 2a had set `api_prefix: "/engineered-orders"` — a *resource collection*, not a global prefix — so the linter searched for `/engineered-orders/component-allocations` and never matched the real `/component-allocations`.

Convention check against the shipped examples: `example-commercial-shipping-v1.yaml` uses `api_prefix: /voyage-manifests` with all 28 endpoints under that single segment, likewise `example-hospital-shifts-v1.yaml` (`/treatment-plans`, 28 endpoints). So the intended convention is single-root, and endpoint `path:` values INCLUDE the prefix (they are full paths, not prepended). This scaffold is genuinely multi-root: 127 endpoints across **21** top-level segments (`/engineered-orders` 20, `/factory-acceptance-tests` 11, `/commissioning-jobs` 9, `/suppliers` 8, `/warranty-claims` 8, ... `/_clock` 1).

Empirical probe on a throwaway copy in /tmp with `api_prefix: ""` → **41 violations drop to 14**, all 27 FK findings clear. Applied to the real file (backup at `SCAFFOLD.yaml.prefixbak`):
`api_prefix: ""   # multi-root scaffold: all 127 §1.5 paths are absolute/full paths across 21 resource families; no single shared prefix`

Deliberate, documented deviation from the single-root example convention. Justification: the 20 entities do not form one resource tree (Supplier, TestBay, WitnessParty, CommodityIndexPoint are not sub-resources of an EngineeredOrder), and since paths already carry their own full prefix, `""` is the truthful value. It is also the SAFER value downstream — a non-empty `api_prefix` invites doc/test/impl generators to prepend it and emit `/engineered-orders/suppliers`.

### The remaining 14 are real, and split into two kinds

Read the linter's own semantics before "fixing" anything, which mattered: **rules (b) and (c) are deliberately skipped for negative-test triggers** (scaffold_lint.py:525-528 + `is_negative_trigger` at :309) — a negative test is *supposed* to send a forbidden role/payload. Detection is either (i) the call captures `$.data.error_id` / `$.data.message`, or (ii) the instance name matches `_NEGATIVE_NAME_RE` (`_cannot_`, `_input_ignored`, `_extra_field`, `_returns_forbidden`, …). Rule (e), by contrast, applies to positive AND negative tests by design (:490-493).

So: 3 of the 14 are valid probes the linter merely failed to RECOGNISE as negative (bogus-role `ERR_UNKNOWN_ROLE`, CustomerWitness list denial, client-supplied-system-fields-ignored). Those get their polarity declared, NOT weakened or deleted. The other 11 are genuine bugs.

Also found one true internal contradiction: §1.1 `LongLeadComponent.allocation_policy` declares `default: PREEMPTIBLE`, yet §1.5 `POST /suppliers/{id}/long-lead-components` listed `allocation_policy` as REQUIRED — while corner instance `create_long_lead_component_omitting_allocation_policy_defaults_to_preemptible` tests exactly that default. A field with a server-side default must not be a required input; the endpoint is wrong, so it becomes `"allocation_policy?"` (quoted — PyYAML rejects bare `token?` in a flow sequence).

Dispatched a fix subagent with all 14 pre-diagnosed: 1 edit to SCAFFOLD.yaml, 10 to the difficulty design (5 missing required payload fields on warranty/commissioning setup calls, 1 more `mobilization_at`, 2 OCC literals `9999` → `"${comp_v} - 1"` preserving the ERR_STALE_COMPONENT_VERSION polarity, 2 role corrections incl. `PlantAdmin` → `MaterialsPlanner` on start-production), 3 to the corner design (1 rename to `..._extra_field_input_ignored`, 2 `$.data.error_id` captures). Explicitly forbidden: deleting instances to silence the linter, or editing scaffold_lint.py.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — COMPLETE — 2026-08-31T22:05:00.000Z

First attempt died with an API error ("unexpected error during processing") at the line "Now I have everything I need. Writing the file in small chunks." — all reading done, zero bytes written. Resumed the SAME agent (preserving the completed reads, which are the expensive part) with a tightened tactic: make the FIRST tool call a small `Write` (<60 lines, one section) to get bytes on disk, verify it parses, then append remaining sections one at a time at <100 lines each. That worked.

Subagent summary, verbatim:

> Done. `SCAFFOLD_CORNER_DESIGN.yaml` is complete.
>
> **Final state**
> - **3069 lines**, parses cleanly with exactly one top-level key: `['scaffold_corner_design']` (a list of 9 section blocks).
> - **77 instances, all non-stub, 0 `excluded_because:` stubs.** (No stubs because SCAFFOLD_DIFFICULTY_DESIGN.yaml did not exist while writing, so no §1.8 `difficulty_instance` name could be cited safely.)
>
> **Per-section counts (non-stub / stub)**
> | section | instances |
> |---|---|
> | entities | 10 / 0 |
> | state_machines | 12 / 0 |
> | calculations | 7 / 0 |
> | validations | 14 / 0 |
> | endpoints | 7 / 0 |
> | errors | 10 / 0 |
> | rbac | 9 / 0 |
> | cross_cutting_complexity_layers | 5 / 0 |
> | consistency_model | 3 / 0 |
>
> **Verification run programmatically (all clean)**
> - Top-level keys exactly `['scaffold_corner_design']`.
> - 77 instance `name:` values, **zero duplicates**.
> - Every `call:` path (with `${var}` / literal UUID segments normalised to `{id}`) and every path mentioned in `assert` prose resolves to a real row in `API_DIGEST.txt`; **0 unknown paths**.
> - Every `ERR_*` token referenced exists in `API_DIGEST.txt`; **0 unknown error ids**.
> - Every instance has `name`, `claim_type`, `grounds`, `distinguishing_aspect`, `test_recipe` with a non-empty `assert`.
> - **Placeholder closure holds**: every `${var}` in payloads, paths and asserts is bound by an earlier `captures:` in the same recipe.
> - Every `as:` is one of the 13 declared roles, except two deliberate negatives: `as: null` (P1 ERR_MISSING_AUTH_HEADER — headers omitted) and `as: Machinist` (P2 ERR_UNKNOWN_ROLE).
>
> **Coverage highlights added this session**
> - `errors`: P1 missing-auth-beats-404, P2 bogus role vs. P2 entity-backed `CustomerWitness` with an unbacked X-User-ID, P28 string-typed integer, P56 duplicate `(commodity, index_month)`, P68 empty index table, P45 DRAFT report pinned by a label, P61 duplicate witness invite, P10 / P9 existence-before-state (path id and body FK).
> - `rbac`: P3 denials for `create_engineered_order`, `start-production` (no PlantAdmin hierarchical override; contrasted against the 409 a MaterialsPlanner would get), `disposition`, `suspend_supplier`, `financial-summary`; `CustomerWitness` allowed on `get_engineered_order` but 403 on `list_engineered_orders`; P4 ERR_NOT_ORDER_OWNER (only reachable on `create_engineered_order`, the sole SalesEngineer write); P5 segregation of duties; P6 witness identity mismatch.
> - `cross_cutting_complexity_layers`: both declared OCC rules (`expected_engineered_order_version` → 412 stale order, `expected_component_version` → 412 stale component, each staled by a real intervening write and then retried with the fresh version), ordering-sensitive commit→order cascade, FINAL vs PROVISIONAL variant divergence (ERR_INDEX_WINDOW_EMPTY), and `version_pinning_on_approval` (`released_drawing_revision` stays 1 after revision 2 is opened and submitted).
> - `consistency_model` (`immediate`): reservation counters, computed `financial-summary` after PATCH, supplier receipt counter — each asserted on the request immediately following the write plus a repeat read to rule out deferred settlement.
>
> Note: as instructed I did **not** run `scaffold_lint.py`; the concurrent §1.8 difficulty agent was still running, so a joint lint pass is still owed once that file lands.

Orchestrator independently verified: 3069 lines; top keys exactly `['scaffold_corner_design']`; 9 section blocks with per-section counts matching the table above; 77 instances, 77 unique names, 0 duplicates.

**Open item flagged for after 2b lands:** corner design emitted 0 `excluded_because:` stubs because §1.8 did not exist yet, so queue B could not cite §1.8 `difficulty_instance` names to de-duplicate. Queue A (§1.8) and queue B (§1.9) may therefore contain overlapping probes. Check `scaffold_lint.py` output for overlap/duplication complaints once both files exist, and run a dedup reconciliation pass if it flags any.

### Step 2a attempt #9 (resume of same agent) — FAILED, no new bytes

Resumed agent died again: "API Error: Server error mid-response" (second consecutive server error, distinct from the earlier 600s watchdog class). Last trace line: "§1.4 validations — appending the priority ladder." File still **2829 lines** — the §1.4 heredoc never landed.

Diagnosis refinement: ~350-line appends are ALSO too large a unit of work in this environment. The chunk size that survived §1.0–§1.3 was luck at the margin; the failure point is now consistently "composing one big append". Two independent mitigations for attempt #10:

1. **Vocabulary digest instead of self-read.** Generated `VOCAB_DIGEST.txt` (142 lines) mechanically from the on-disk scaffold via `yaml.safe_load` — api_prefix; all 17 state machines with entity, state_dimension, initial/terminal states, full state token lists and transition events; all 5 concurrency rules with rule_id/occ_field/write_endpoint/error_id/http_status; all 16 calculation names; all 20 entities with parent/common_fields/full field lists. This lets a fresh agent write §1.4–§1.7 with exact token spellings WITHOUT loading the 2829-line scaffold, which was the bulk of the dead agent's context. (Digest is a scratch artifact — delete before the task is considered complete; it is not part of the expected output tree.)
2. **Append cap cut from 350 → 120 lines**, with each of the four remaining sections split across multiple appends (validations by priority band, endpoints by resource). More checkpoints ⇒ an API error costs ≤120 lines instead of everything in flight.

Reading budget for the continuation agent is now just SKILL.md offset=438 limit=124 (§1.4–§1.7 only) + the 142-line digest. Cross-reference obligations passed through explicitly: every validation/endpoint error_id must be defined in errors; the 5 concurrency write_endpoints must appear in endpoints; every non-`system:` transition event in the digest must have a matching endpoint while `system:` cascades must NOT get invented endpoints; every endpoint needs an rbac entry; endpoint ids unique.

Step 2a-cont launched (fresh agent, dead agent's context abandoned as unrecoverable).

### Step 2a attempt #8 — PARTIAL, work preserved (first durable progress in 8 runs)

Split-step 2a subagent terminated early: "API Error: The system encountered an unexpected error during processing" (not the 600s watchdog this time). Last trace line: "Now the validation ladder."

**The chunked-append protocol worked as designed — 2829 lines survived on disk.** Verified with `yaml.safe_load`: parses cleanly. Top keys present: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (**20**), state_machines (**17**), concurrency_rules (**5**), calculations (**16**, ending at `warranty_window_expiry`, matching the file tail → section complete).

So §1.0–§1.3 are DONE and must not be regenerated. Remaining: §1.4 validations, §1.5 endpoints, §1.6 errors, §1.7 RBAC.

Resumed the SAME agent via SendMessage rather than spawning a fresh one — it retains the design context (exact entity field names, the status vocabularies of all 17 state machines, the 16 calc ids) that the remaining four tables must stay referentially consistent with. A fresh agent would have to re-derive those vocabularies from a 2829-line file and would likely drift on spellings. Resume instructions re-pin the append protocol and the cross-table integrity rules (every §1.4/§1.5 error_id exists in §1.6; every §1.5 endpoint covered in §1.7; endpoint ids unique).

### Step 2 attempt #7 — FAILED (no output)

Monolithic Step 2 subagent (all three YAMLs, one agent) stalled: "no progress for 600s (stream watchdog did not recover)". Last trace line: "I'll start by reading the skill specification." `find . -type f` after failure → still only worklog.md + workspace/INSTRUCTION.md. Zero bytes written.

Diagnosis: the monolithic framing is the failure mode, not bad luck. Step 2's spec `skills/prd-bench-scaffold-generator/SKILL.md` is 774 lines / 73KB (long lines), the examples dir holds 14 files of 743–1846 lines each, and the step is asked to emit ~1200–1800 lines of YAML across three files. Reading spec + a large example, then streaming one enormous Write, exceeds the 600s stream watchdog before any tool call lands.

Remediation for attempt #8 — split Step 2 into three bounded subagents with capped reading and incremental writes:
- **2a** SCAFFOLD.yaml (§1.0–§1.7) — reads SKILL.md in 3 bounded Read ranges (1-230, 222-561, 721-774), explicitly forbidden from reading §1.8/§1.9 (lines 562-720), at most ONE example file. Writes §1.0/§1.1 with Write then appends §1.2→§1.7 in five `cat >> <<'YAMLEOF'` heredoc chunks of ≤350 lines each, `wc -l` after each.
- **2b** SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — reads SKILL.md 562-670 + finished SCAFFOLD.yaml.
- **2c** SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — reads SKILL.md 671-720 + finished SCAFFOLD.yaml.
2b and 2c depend on 2a and run concurrently after it. Chunked appends mean a mid-generation stall now leaves durable partial progress instead of nothing. `scaffold_lint.py` (validates §1.8/§1.9 against the §1.5 endpoint table) is deferred until all three files exist.

Step 2a launched.

## Step 0 (resume audit #7): — 2026-08-31T20:45:00.000Z

Seventh resume-mode audit. `find . -type f` → exactly two files: `worklog.md` and `workspace/INSTRUCTION.md` (53 lines; `diff -q` vs project-root `INSTRUCTION.md` → IDENTICAL, non-truncated). Still absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Verdict: Step 1 valid, Step 3 valid — neither redone. Step 2 has produced no output across six prior crashed runs; this run's Step 2 subagent is instructed to Write each of the three scaffold files to disk immediately as it finishes them rather than buffering all three to the end, so a crash mid-generation leaves partial durable progress. Step 2 launched.

## Step 5: Generate unit tests — COMPLETE — 2026-09-01T00:35:00.000Z

**test_helpers/ = 9 files, 2655 lines; test_suite/ = 23 modules + conftest, 6301 lines; 96 tests collected.**

Subagent summary, verbatim:

> The suite is complete and clean.
>
> ## Files created
>
> `test_helpers/` (2,655 lines): `__init__.py` 119, `api_client.py` 716, `api_errors.py` 207, `assertions.py` 187, `constants.py` 185, `factories.py` 306, `fixtures.py` 541, `test_users.py` 89, `types.py` 305.
>
> `test_suite/` (6,278 lines, 23 test modules + `conftest.py` 23):
>
> | file | lines | tests |
> |---|---|---|
> | test_01_escalation_adjustment_variants.py | 191 | 2 |
> | test_02_supplier_quality_index.py | 352 | 2 |
> | test_03_arc_flash_label_values.py | 192 | 2 |
> | test_04_warranty_waterfall.py | 364 | 2 |
> | test_05_release_penalty_tiers.py | 114 | 1 |
> | test_06_witness_lifecycle.py | 323 | 2 |
> | test_07_bay_scheduling.py | 239 | 2 |
> | test_08_fat_retest_revert.py | 149 | 1 |
> | test_09_cascades.py | 356 | 2 |
> | test_10_error_precedence.py | 354 | 3 |
> | test_11_site_storage.py | 202 | 1 |
> | test_12_component_conservation.py | 235 | 1 |
> | test_20_entities.py | 343 | 10 |
> | test_21_drawing_state_machine.py | 174 | 5 |
> | test_22_order_lifecycle_state_machine.py | 347 | 7 |
> | test_23_calculations.py | 344 | 7 |
> | test_24_validations_shape_and_uniqueness.py | 291 | 7 |
> | test_25_validations_cross_entity.py | 293 | 6 |
> | test_26_endpoints.py | 220 | 7 |
> | test_27_errors.py | 341 | 9 |
> | test_28_rbac.py | 340 | 9 |
> | test_29_cross_cutting.py | 350 | 5 |
> | test_30_consistency.py | 164 | 3 |
>
> **Total: 96 tests.**
>
> ## Design-index coverage
>
> - Queue A (§1.8 difficulty): **21 of 21 translated**, 0 skipped. One is a partial translation — `Difficulty/priority_pair_validation_conflict/label_verify_sod_p5_beats_label_stale_p43_then_same_row_yields_p43_with_a_clean_actor` asserts only the P5-over-P43 arm; the designed "same row with a clean actor then yields P43" second arm is omitted because a clean actor on that row hits rung 35 (`ERR_INVALID_STATE_TRANSITION`) before rung 43, so the design's asserted outcome is not PRD-derivable.
> - Queue B (§1.9 corner): **75 of 77 translated, 2 skipped**.
>
> ### Skipped instances
> - `Corner/validations/warranty_claim_without_any_complete_commissioning_job_returns_window_unavailable` — **filter condition 2** (PRD does not uniquely derive the outcome): PRD 3.9 line 356 places `ERR_WARRANTY_WINDOW_UNAVAILABLE` on issue-rma; claim create (line 354) declares no window check.
> - `Corner/errors/compliance_label_pinning_a_draft_test_report_returns_test_report_not_issued` — **filter condition 2**: PRD 3.6 line 300 places `ERR_TEST_REPORT_NOT_ISSUED` on label *generation*; label *create* (line 298) has no such precondition.
>
> ## Verification performed
>
> - `python3 -m py_compile` clean on all 32 helper + suite files.
> - Helper/API checker clean on all 23 modules: no `missing:`, `unused:`, or `api_missing:` entries.
> - Tag audit: 96 tests, 96 `Design:` lines, each exactly one and positioned as the final docstring line; zero duplicates; all 96 tags resolve to real `name:` entries in the two design yamls (21 distinct queue-A, 75 distinct queue-B).
> - Citation audit (verbatim-fragment matcher against `workspace/PRD.md`, with unicode em-dash/en-dash/arrow sensitivity): **0 problems**. This final pass fixed ASCII-dash drift and paraphrase in `test_02`, `test_03`, `test_06`, `test_10`, `test_12`, `test_20`, `test_21`, and rewrote the `test_28` RBAC grant citation to quote both endpoint rows verbatim from the PRD 4 table.

Orchestrator independently verified (all claims confirmed):
- `python3 -m py_compile` over all 32 files → **ALL COMPILE OK**; `pytest --collect-only` → **96 tests collected in 0.42s** (no collection errors).
- **No `skip`/`xfail`/`@skip` markers** anywhere in `test_suite/` or `test_helpers/`. Gaps were left as gaps, per contract.
- AST-based tag audit (parse every `def test_*`, read its docstring): **96 tests, 0 untagged, 0 dual-tagged, 0 with the tag off the final docstring line, 0 unresolved tags**. Queue A **21/21 distinct**, queue B **75/77 distinct**, **0 duplicate instances** across the whole suite.
- The two queue-B skips were independently re-derived from `PRD.md`: `ERR_WARRANTY_WINDOW_UNAVAILABLE` occurs at exactly one place in the PRD body (line 356, issue-rma: "Issuing the return authorization ... is where the warranty window is tested"), and `ERR_TEST_REPORT_NOT_ISSUED` at exactly one place (line 300, label **generation**). Both corner instances asserted the error on a *different* endpoint than the PRD assigns it to, so condition 2 genuinely fails. **Correct skips, not weakened assertions.**

Note on the earlier queue A/B overlap concern: because §1.9 was authored before §1.8 existed, it emitted 0 `excluded_because:` stubs and could have duplicated queue-A coverage. The audit above shows **0 duplicate design instances**, so any residual overlap is semantic rather than literal; it is benign because every test still asserts a PRD-traceable rule. Watch for it in Step 7 only if two tests fail on an identical rule.

## Step 7: Test-fix loop — LAUNCHED — 2026-09-01T00:45:00.000Z

One long-lived diagnostic subagent owns the whole loop (run sweep → diagnose → fix → rerun), so the domain model, fixture shapes and cross-iteration adjudications survive between rounds instead of being re-derived from 12k+ lines each time.

Iteration unit is the **parallel 8-round stability sweep**: 8 concurrent `prd-bench-local-run` invocations, `--isolation per-test-server` (server killed and relaunched via `start.sh` before each of the 96 tests), `--timeout 120 --test-timeout 30`, no `--api-url` so each round claims its own port from `~/.cache/prd-bench-local-runner/ports.tsv` under `flock`. Exit condition is `passed == total` in **all 8** rounds; the failure set each iteration is the **union** across rounds, so a test that passes in 7 rounds and fails in 1 still counts as failing — that is the flakiness signal. No iteration cap.

Host capacity checked before launch: 32 cores, 111 GB available — enough for the ~8× peak load of the concurrent sweep.

Two task-specific notes added to the agent's brief beyond the standard protocol:
1. Deleting a test must also report its `Design:` tag, since that tag is exactly the "scaffold rule that drove the test's generation" the cardinal rules require in deletion notes. Tags on surviving tests must not be edited.
2. Warned not to infer "tests hang" from a Bash tool timeout — 96 tests × per-test reboot × 8 rounds is genuinely slow — and to poll the results files or background the sweep instead.

Reminded that the arbiter of any dispute is `workspace/PRD.md`, never SCAFFOLD.yaml, even though the scaffold is readable for diagnosis; and that `start.sh`'s conditional Flask install is deliberate and must not be made unconditional.

## Step 7: Test-fix loop — COMPLETE — ALL GREEN — 2026-09-01T01:00:00.000Z

**4 iterations (32 rounds). Final state: 96/96 in all 8 parallel rounds, twice consecutively. 0 tests deleted; 96 tests retained.**

Trajectory: baseline 71/96 → 95/96 → 96/96 → 96/96 (confirming re-run). Notably every one of the 25 baseline failures failed in **8 of 8 rounds** — fully deterministic, zero flakiness signal — so the 8-round sweep found no timing-sensitive bugs in this task; its value here was confirming their absence.

Subagent summary, verbatim:

> Two consecutive all-green sweeps. Done.
>
> ## Summary
>
> **Iterations run:** 4 full 8-round parallel sweeps (32 rounds total).
> 1. Baseline — 71/96 in all 8 rounds (25 failures, each failing 8/8: fully deterministic, no flakiness signal).
> 2. After the main fix batch — 95/96 in all 8 rounds (1 failure, 8/8).
> 3. After the final partial-coverage split — **96/96 in all 8 rounds**.
> 4. Confirming re-run — **96/96 in all 8 rounds**, union of failures empty.
>
> All 96 tests are retained; test count unchanged.
>
> ### Tests deleted
> None. One **assertion** was removed under STEP 1c (partial coverage), not a whole test:
>
> - `test_suite/test_02_supplier_quality_index.py::test_retracting_a_published_analysis_restores_indices_but_not_allocations` — removed the trailing `assert_order_state(order_c, production_posture="RESTRICTED", posture_reason_codes=["MATERIAL_INCOMPLETE"])`. **Category: BRANCH-ASYMMETRIC SIDE EFFECT.** PRD L364 names the forward cascade's posture hop verbatim ("The fourth hop follows from those releases: each affected order recomputes its `production_posture` to `FROZEN` with the reason `COMPONENT_QUARANTINE`"), while L370's exhaustive enumeration of retraction effects omits any posture recompute, and L102's trigger is "recomputed from scratch after every mutation that touches **any child of the order**" — the retraction touches a claim on a *different* order and the shared component, neither of which is a child of `order_c`. Both a recompute-on-read implementation (RESTRICTED) and a literal L102-trigger implementation (stale FROZEN) are PRD-faithful, so the assertion is not uniquely derivable. Everything else in the test — the bit-for-bit index restoration, the claim revert, the component returning to ACTIVE, and the allocation *not* being un-released — was kept. `Design: Difficulty/compensating_invariant/far_retract_restores_supplier_indices_exactly_but_never_un_releases_the_allocations` (the tag was left intact on the surviving test).
>
> ### Fixes applied to `test_helpers/`
> - `assertions.py` — added `assert_instant_equals(actual, expected)` (plus `_to_instant`), comparing two ISO-8601 instants as points in time truncated to the second. PRD §2.10: "Instant comparisons are made at second granularity"; PRD pins 3 fractional digits only for `created_at`/`updated_at` (§2.4) and is format-silent for the 15 §2.10 server-written timestamps, so a string-equality assertion was over-specifying the wire format.
> - `__init__.py` — exported `assert_instant_equals`.
>
> ### Fixes applied to `test_suite/`
> - 15 exact-timestamp string comparisons converted to `assert_instant_equals` across `test_04:226` (`energized_at`), `test_06:109,130` (`confirmed_at`, `window_end_at`), `test_07:106,134,193,212,218,237` (`window_end_at`), `test_09:297` (`published_at`), `test_21:86,136` (`submitted_at`), `test_22:98,132` (`committed_at`, `released_at`), `test_23:331` (`window_end_at`) — same reason as above.
> - `test_03_arc_flash_label_values.py` — `_order_with_issued_report` now inlines create/schedule/start/report/issue instead of `run_fat_to_conclusion`, leaving the FAT `IN_PROGRESS`. PRD §3.6 gates report creation on an `IN_PROGRESS` parent test, and label generation never requires the FAT to have concluded, so the old fixture built a precondition on which the ceiling test's second report was unmeasurable.
> - `test_08_fat_retest_revert.py` — expected bay `scheduled_hours_total` 16 → 8. PRD L264: "tests in `REQUESTED`, `PASSED`, `FAILED` or `ABANDONED` never occupy a bay", so only `fat_three`'s 8 hours remain.
> - `test_09_cascades.py` — expected bay `scheduled_hours_total` 8 → 0 (PASSED first attempt plus FAILED second: nothing occupies the bay).
> - `test_12_component_conservation.py` — dropped the explicit `201` on `POST /long-lead-components/{id}/receipts`. PRD L380: "A successful creation returns HTTP 201; every other successful operation... returns HTTP 200"; a receipt creates no resource family (§2.5 lists 21, none of them a receipt) and the body is the mutated component. This also resolved a suite-internal contradiction with `test_29:122`, which asserted 200 for the same endpoint.
> - `test_22_order_lifecycle_state_machine.py` — `_committed_order` now calls `release_design`, since PRD §3.4 requires `engineering_status == DESIGN_RELEASED` to commit; SM6 asserts `DESIGN_RELEASED`; SM11 reaches its `ERR_DESIGN_NOT_RELEASED` precondition through the PRD §3.2 re-opening path (create + submit a higher revision round → `SUBMITTAL_IN_REVIEW`), which is the only PRD-legal way to be `MATERIAL_ALLOCATED` without a released design.
> - `test_29_cross_cutting.py` — added `release_design` to the material-cascade test for the same §3.4 reason.
>
> ### Fixes applied to `workspace/implementation/`
> - `routes_suppliers.py` / `create_receipt_event`, `receive_component` — `envelope.created` → `envelope.ok` (PRD L380: only creations answer 201).
> - `routes_suppliers.py` / `check_component_usable` — added `as_target` flag; on the reservation and receipt paths the component is a body-borne reference, and PRD §3.4 pins the outcome verbatim ("A component that is `QUARANTINED` or `OBSOLETE` is rejected with `ERR_COMPONENT_QUARANTINED`"; "Receiving against a component that is not `ACTIVE` is rejected with `ERR_COMPONENT_QUARANTINED`"). `routes_allocations.py` / `create_allocation` and the receipt path now pass `as_target=False`; the commit path, where PRD names no error id, is unchanged.
> - `routes_tests.py` / `schedule_fat` — removed `common.refresh_fat_witness_aggregate(fat)`. PRD §3.5's aggregate trigger is "Whenever any assignment on a test changes state"; scheduling is not an assignment change, and L266 lists no witness effect.
> - `routes_tests.py` / `start_fat` — source states widened to `("BAY_SCHEDULED", "WITNESS_CONFIRMED")` per the endpoint table L443 ("BAY_SCHEDULED or WITNESS_CONFIRMED -> IN_PROGRESS"); without this a `witness_required == false` test would be unstartable.
> - `routes_commissioning.py` / `energize_job` — replaced the `_refresh_job` call with an aggregates-only refresh. PRD L340 says energization only "recomputes the completion ratio"; L348 pins the `PUNCH_OPEN → COMPLETE` edge to "After every punch item state change", so the job must stay `PUNCH_OPEN`.
> - `routes_witness.py` / `create_assignment` — removed the `_check_blackout` call. PRD L270 names only `ERR_FAT_NOT_ADMINISTRABLE` and `ERR_WITNESS_ALREADY_ASSIGNED` as invite gates; the travel gate is a confirmation gate (L274).
> - `routes_shipment.py` / `create_release` — `if total > 10000` → `if total != 10000`, per PRD L316: "must equal exactly 10000, and any other total — short or over — is rejected with `ERR_STAGE_SHARE_TOTAL_INVALID`".
> - `routes_orders.py` / `create_order` — applied the rung-4 `SalesEngineer` ownership check against the body's `owning_sales_user_id` before payload validation (rung 4 precedes rungs 27-31), per PRD L25: "On every order-scoped write a `SalesEngineer` performs, the header `X-User-ID` must equal the `owning_sales_user_id` recorded on the order in scope; otherwise... `ERR_NOT_ORDER_OWNER` (HTTP 403)."
>
> No implementation check that PRD requires was weakened (notably `ERR_DESIGN_NOT_RELEASED` on commit and start-production was preserved and the tests were corrected instead), no skip/xfail was added, no error-id assertion was downgraded, no data is seeded, storage remains in-memory dicts, and `start.sh` still installs Flask only on `import flask` failure.

Orchestrator independently verified:
- Read all 8 `results.*.json` from the agent's final sweep: **every round `passed=96 total=96 failed=0`**. File mtimes were ~90 s old at inspection, confirming a genuinely fresh run rather than stale evidence.
- Then ran **my own independent 8-round sweep** (separate `verify.*.json` targets so the agent's evidence could not be overwritten): **all 8 rounds 96/96, 0 failed**. That is a third consecutive all-green sweep — 24 green rounds in total.
- Post-fix invariant re-check, since Step 7 had write access to everything: `pytest --collect-only` still **96 tests**; **no `skip`/`xfail`** introduced; AST tag audit still **queue A 21/21, queue B 75/77, 0 problems** (no tags stripped or broken while editing); **no disk-persistence** calls; **no wall-clock** use outside `clock.py`; `start.sh` byte-identical, conditional Flask install intact.

Assessment of the two headline judgement calls:
- The single removed assertion is a correct 1c partial-coverage split, and the reasoning is the strongest kind — it turns on the PRD's own recompute *trigger* (L102, "any child of the order") not reaching the retraction's blast radius, so two PRD-faithful readings genuinely diverge. The valuable half of that test (exact index restoration, allocations *not* un-released) survives, and the `Design:` tag was preserved, so queue-A coverage stays at 21/21.
- Direction of blame looks right throughout: 7 of the fixes went to tests and 8 to implementation, and the agent explicitly refused to strip `ERR_DESIGN_NOT_RELEASED` when tests couldn't satisfy it, fixing the fixtures instead — the exact trap the cardinal rules warn about.

Scratch `verify.*.json` files were deleted after verification; the agent's `results.*.json` were left in place as the run's evidence.

## Step 8: Finalize PRD — COMPLETE — 2026-09-01T01:15:00.000Z

**workspace/PRD_FINALIZED.md = 601 lines (from 599). 8 edits: 7 in-paragraph revisions + 1 inserted paragraph. No sections added or removed.**

Step 8 did NOT qualify for the skip condition — Step 7 ran 4 iterations with 8 implementation fixes, 7 test fixes and 1 assertion split, so there were real PRD-silence sites to pin.

Subagent summary, verbatim:

> Done. `PRD_FINALIZED.md` is in place with eight targeted edits.
>
> ## Size delta
> - `PRD.md`: 599 lines / 18,794 words
> - `PRD_FINALIZED.md`: 601 lines / 19,345 words
> - **+2 lines (+0.33%), +551 words (+2.9%)**; 8 source lines revised, 1 paragraph inserted. No sections added or removed.
>
> ## Changes
> - **§2.1 (Roles & Authorisation) — revise** — pinned that on order creation the rung-4 `SalesEngineer` ownership comparison targets the body's `owning_sales_user_id` and runs ahead of the payload rungs, and that it is skipped (passes) when that field is absent or non-string — `implementation/routes_orders.py:79-82`, `implementation/rbac.py:206-211`
> - **§2.6 (Derived Production Posture) — insert** — new paragraph: recomputation is triggered by writes touching the order's own row or a row beneath it; a write elsewhere that only changes an input to another order's posture leaves that order's stored posture as last computed (shared component leaving `QUARANTINED`); plain read/list report stored values while `/posture` and `/financial-summary` recompute and persist on difference — `implementation/posture.py:123-140`, `implementation/routes_orders.py:121-125,265,273`, `implementation/routes_warranty.py:349-366`
> - **§2.9 (Conservation Invariants — Bay hours) — revise** — the subtracting events are any exit from the three occupying statuses, i.e. abandon **or** conclude-as-fail **or** conclude-as-pass, because the total is a pure aggregate — `implementation/calc.py:215-221`, `implementation/routes_tests.py:300-303`
> - **§2.10 (Logical Clock) — revise** — all server-written instants (the 15 named stamps, `created_at`/`updated_at`, envelope timestamp, arithmetically derived `window_end_at`) render as ISO-8601 UTC with exactly three fractional digits + `Z`; caller-supplied instants are stored/echoed byte-for-byte with no renormalisation — `implementation/clock.py:26-33`, `implementation/routes_tests.py:207`, `implementation/validation.py:59-60`
> - **§3.4 (Components & Allocations, commit) — revise** — commit-path component dispositions: `QUARANTINED` → `ERR_COMPONENT_QUARANTINED`, `OBSOLETE` → `ERR_TERMINAL_STATE`, contrasted with the reservation/goods-receipt paths where both report `ERR_COMPONENT_QUARANTINED` — `implementation/routes_suppliers.py:43-57`, `implementation/routes_allocations.py:45,140`
> - **§3.5 (Witness invitation) — revise** — invitation also applies the credential gate (`status` must be `ACTIVE`; where a window exists, `credential_expires_at` strictly after `window_start_at`; `REQUESTED` test → party-status only), while blackout and day-capacity remain confirmation-only — `implementation/routes_witness.py:151-152,22-31,210-217`
> - **§3.5 (Starting the test) — revise** — start accepts `BAY_SCHEDULED` **or** `WITNESS_CONFIRMED` as source, noting only an assignment state change re-evaluates the witness aggregate — `implementation/routes_tests.py:226`, `implementation/common.py:182`
> - **§4 (Endpoint table preamble) — revise** — defined "creation" as persisting a new row of its own family, and pinned `/suppliers/{id}/receipt-events` and `/long-lead-components/{id}/receipts` as non-creations returning 200 with the mutated parent as `data` — `implementation/routes_suppliers.py:117,227`
>
> ## Pre-edit search log
> 1. **§2.1 rung 4** — (a) subject: scope/timing of the `SalesEngineer` ownership check on creation. (b) grepped `check_order_ownership` (all 4 callsites: `routes_orders.py:81,148,174,200`), read `rbac.py:206-211` and the full `ENDPOINT_ROLES` table to confirm `SalesEngineer` appears on no other write endpoint (so no parallel write path can contradict the wording). (c) said "the value compared is the body's `owning_sales_user_id`" rather than "the only place rung 4 fires", leaving the general order-scoped rule intact.
> 2. **§2.6 posture** — (a) subject: recompute trigger set, staleness across orders, and which reads recompute. (b) grepped every `posture.refresh` / `refresh_by_id` callsite across `routes_orders.py`, `routes_drawings.py`, `routes_escalation.py`, `routes_tests.py`, `routes_witness.py`, `routes_reports.py`, `routes_shipment.py`, `routes_commissioning.py`, `routes_warranty.py`, `common.py:235,254,261`; read `posture.refresh` (touch-only-on-change), `common.release_component_reservations` → `auto_material_edges` (so supplier suspension *does* refresh victims), `routes_warranty.py` publish/retract, `routes_suppliers.py` `release_quarantine` (no refresh); confirmed `get_order`/`list_orders` do not refresh and `check_posture_blocked` does. (c) wrote "writes that touch that order's own row or a row beneath it, **and by the posture-gated checks and computed reads named below**" to cover `check_posture_blocked`; used "an order … whose own rows the request never touches" rather than claiming non-child writes never refresh anything.
> 3. **§2.9 bay hours** — (a) subject: which events change `scheduled_hours_total`. (b) grepped `refresh_bay_hours` / `scheduled_hours_total` (`calc.py:215`, `routes_tests.py:41,148,210,302,334`); read `OCCUPYING_STATES`, `conclude_fat` (both arms refresh), `abandon_fat`, retest-predecessor abandonment; checked `PATCH /test-bays` does not recompute. (c) phrased as "any exit from those three statuses" with the aggregate rationale, instead of enumerating a closed list of endpoints.
> 4. **§2.10 instant rendering** — (a) subject: rendering of server-written vs caller-supplied instants. (b) grepped every `clock.now_str()` / `clock.fmt(` callsite (20 sites incl. `store.py:57,59,70`, `envelope.py:20`, `routes_tests.py:207`), read `clock.fmt`, and grepped `_at"] =` assignments not sourced from the clock (only `routes_shipment.py:302`, which stores a caller value or `now_str()`); read `validation.py:59-60` confirming DATETIME is kept as the raw string. (c) added "any instant the server derives arithmetically such as a test's `window_end_at`" instead of naming a closed field list; left `storage_end_at` unmentioned since it is caller-or-clock sourced and covered by both halves of the rule.
> 5. **§3.4 commit component gate** — (a) subject: error id per component status per path. (b) read `check_component_usable` and all three callers (`routes_allocations.py:45` `as_target=False`, `routes_allocations.py:140` default, `routes_suppliers.py:222` `as_target=False`); cross-checked PRD §3.4 receipt (line 240) and reservation (line 242) prose, which already match `ERR_COMPONENT_QUARANTINED` for both dispositions. (c) scoped the sentence with "on this path" and deliberately omitted the ladder position of `ERR_TERMINAL_STATE` here, since the impl raises it after the posture gate — under-determined rather than a false universal.
> 6. **§3.5 invite gates** — (a) subject: gate set at assignment creation. (b) read `routes_witness.py:140-170` (`check_fat_administrable`, `_check_credential`, duplicate-pair check, derived `blackout_days`), `_check_credential`/`_check_blackout` helpers, `confirm_assignment:202-224`, `reinvite`/`waive` paths, `common.refresh_fat_witness_aggregate` callsites. (c) said the credential gate uses "the same credential terms confirmation applies" and spelled out the `REQUESTED`-no-window case; explicitly negated only blackout and capacity at invite (verified absent), and left the derived `blackout_days` prose in §3.5 untouched since it already matches.
> 7. **§3.5 start-FAT source states** — (a) subject: legal source statuses for start. (b) read `start_fat:226` (`check_state` with both states), `schedule_fat` (no witness-aggregate call), `refresh_fat_witness_aggregate` callsites (witness routes only), plus the §4 table row that already listed both states. (c) added the clause explaining why a `BAY_SCHEDULED` test can be startable rather than restating the aggregate rule, avoiding a second normative claim about when the aggregate runs.
> 8. **§4 creation vs 200** — (a) subject: status code and payload of the two receipt-recording posts. (b) grepped all 20 `envelope.created` sites and counted all 73 POST routes to confirm the two receipt endpoints are the only child-path posts that do not insert a row; read `create_receipt_event` and `receive_component` return statements. (c) defined "creation" generically ("persists a new row of its own family") before naming the two exceptions, so the rule stays derivable rather than becoming a hard-coded endpoint list.
>
> Items in `<step_7_diff>` that I deliberately did **not** patch, because the PRD already determines the behavior: the `test_03` fixture change; `test_22`/`test_29` `release_design` additions (§3.4 line 248 and §3.6 already require `DESIGN_RELEASED`); `create_release`'s `!= 10000` check (§3.7 line 318 states the exact-10000 rule and its error id verbatim); and `energize_job` leaving the job in `PUNCH_OPEN` (§3.8 already pins the completion edge to punch-item state changes).

Orchestrator independently verified:
- `diff PRD.md PRD_FINALIZED.md` → **7 lines removed / 9 added**, matching the claimed 7 revisions + 1 insert (the inserted paragraph plus its blank line).
- Section-header lists are **byte-identical** between the two files: no section added, removed, renamed or reordered.
- Structural payload intact: **127 endpoint rows** and **82 error rows** in both files; `PRD_FINALIZED.md` ends on the same final catalogue row as `PRD.md`, so no truncation.
- Spot-verified the three highest-risk new claims against the implementation rather than trusting the summary:
  - §2.10 — `clock.fmt` (`clock.py`) is `strftime(...) + "%03d" % (microsecond // 1000) + "Z"`, exactly three fractional digits, **and** short-circuits `if isinstance(dt, str): return dt`, so caller-supplied instants really do pass through byte-for-byte. Both halves of the edit are true.
  - §2.1 — `create_order` reads `owner = payload.get("owning_sales_user_id")` and calls `rbac.check_order_ownership` only under `if isinstance(owner, str):`, **before** `validation.validate(...)`. The documented skip-when-absent-or-non-string behaviour and the rung-4-before-payload ordering are both accurate.
  - §4 — `routes_suppliers.py:117` and `:227` both `return envelope.ok(...)`, confirming the two receipt endpoints answer 200.
- Good discipline worth noting: the agent declined to patch 4 of the `<step_7_diff>` items after finding the PRD already determined them (exact-10000 stage shares, `DESIGN_RELEASED` on commit, the punch-driven completion edge, and the `test_03` fixture change, which was a pure test bug). That restraint is what keeps the diff at +0.33%.

Minor readability nit (not a defect, left alone): the §3.4 commit edit splices a long em-dash aside into the middle of a requirement list, so the sentence now reads "requires the component to be `ACTIVE` — … — the order's `engineering_status` to be `DESIGN_RELEASED`, …". Still unambiguous, and Step 9 may touch this paragraph anyway.

## Step 9: Complete PRD — COMPLETE — 2026-09-01T01:50:00.000Z

**workspace/PRD_COMPLETED.md = 601 lines, 174,629 chars (from PRD_FINALIZED.md's 601 lines / 144,309 chars). +30,320 chars across 77 diff hunks, 0 line delta — every change is an in-paragraph insert or revision. No new sections, paragraphs or table rows.**

Subagent summary, verbatim:

> Done. `PRD_COMPLETED.md` is complete.
>
> ## (a) Size
>
> | | lines | chars |
> |---|---|---|
> | `PRD_FINALIZED.md` (source) | 601 | 144,309 |
> | `PRD_COMPLETED.md` | 601 | 174,629 |
>
> Char delta **+30,320**; line delta **0** — every change is an in-paragraph insert or revision (77 diff hunks / 78 changed lines). No new sections, no new paragraphs, no new table rows.
>
> ## (b) Changes
>
> **§2 (global rungs)**
> - §2.1 — insert — auth headers are trimmed before examination, so whitespace-only reads as absent — `rbac.py:189`
> - §2.2 — insert — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `envelope.py:13`
> - §2.2 — insert — `api_request_timestamp` reads the logical clock, never the OS clock — `envelope.py:17`
> - §2.3 — insert — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; empty string takes the default — `envelope.py:46`
> - §2.3 — insert — `created_at` ties break on persistence order — `store.py:all_rows`
> - §2.11 — insert — body-borne reference shape failures surface at the existence rungs, not the payload band — `common.py:43`
> - §2.11 — insert — payload band runs as four whole-body sweeps; missing/empty body reads as `{}` — `validation.py:68,36`
> - §2.11 — revise — the terminal rung is subordinate to a transition's own source list — `common.py:61`
>
> **§3.1 orders**
> - insert/revise — length + `rated_kv` range are range violations checked ahead of the uniqueness scan; all derived header fields seeded — `routes_orders.py:83-102`
> - insert — PATCH bounds, `PLANNING`-only gate with the terminal/non-terminal error split, stage rebill, and both computed reads returning the whole order row — `routes_orders.py:128-141,261-274`
> - insert — cancel: `ENG_CLOSED` terminal on the engineering axis (checked first), in-transit refusal id, storage flattening, posture recomputed not stamped — `routes_orders.py:196-258`
> - insert — close-engineering error ids and the forced `ORDER_CLOSED`/`ORDER_FULFILLED` codes — `routes_orders.py:170-193`
> - insert — start-production needs posture *exactly* `OPEN`; terminal fulfilment answers `ERR_TERMINAL_STATE` — `routes_orders.py:144-167`
> - insert — clock response shape; persists nothing — `routes_orders.py:60-66`
>
> **§3.2 drawings**
> - insert — `SUPERSEDED_BY_REVISION` vs `SUPERSEDED_BY_APPROVAL`; cancelled/closed ids sit after the version rung — `routes_drawings.py:37-82`
> - insert — submit gate order and each error id — `routes_drawings.py:114-147`
> - revise — staling touches only labels pinned *strictly below* the new round; `LABEL_STALE` posture only when staling actually occurred — `common.py:165`
> - insert — `notes_count` / BOM flag fall back to stored values when omitted — `routes_drawings.py:166`
> - insert — clause-less order above the escalation threshold refusal and its position — `routes_drawings.py:166`
> - insert — approval side effects — `routes_drawings.py:166`
>
> **§3.3 escalation**
> - insert — month strings shape-policed (`ERR_FIELD_TYPE_INVALID` / `ERR_FIELD_VALUE_OUT_OF_RANGE`) — `routes_escalation.py:22`
> - insert — index-point PATCH bounds; no version minted — `routes_escalation.py:140`
> - insert — clause must belong to the path order (`ERR_CLAUSE_NOT_FOUND`); `SUPERSEDED` refusal — `routes_escalation.py:162`
> - insert — provisional variant's missing point is `ERR_INDEX_POINT_MISSING` — `routes_escalation.py:29`
> - insert — usability covers base month and every window month; zero-weight commodity excluded — `calc.py` escalation
> - insert — dispute reason blank handling, recalculate gates, no order version bump — `routes_escalation.py:266,285`
> - insert — accepted-withdrawal guards and their ids — `routes_escalation.py:313-326`
>
> **§3.4 components/allocation**
> - insert — supplier list filters — `routes_suppliers.py:89`
> - insert — `part_number` uniqueness precedes the suspension check — `routes_suppliers.py:167-170`
> - insert — allocation birth nulls; the two references resolved independently of each other — `routes_allocations.py:82-93`
> - insert — victim tie-break falls to insertion order; `PROTECTED`/ownership refusals presuppose a lower-priority holder — `routes_allocations.py:19-80`
> - revise — commit gates and the `OBSOLETE` → `ERR_TERMINAL_STATE` asymmetry — `routes_allocations.py:130-152`, `routes_suppliers.py:43-57`
> - insert — `release_reason`; `FAT_COMPLETE` / `CLOSED` ids on the COMMITTED branch only — `routes_allocations.py:155-183`
> - insert — release-quarantine and obsolete refusal ids; `obsolete_reason` — `routes_suppliers.py:230-262`
>
> **§3.5 bays / FAT / witnesses**
> - insert — bay rating bound and its check order; the schedule read returns FAT objects — `routes_tests.py:25-95`
> - insert — FAT birth nulls — `routes_tests.py:98-152`
> - insert — FAT creation's fulfilment gate precedes the three bay checks — `routes_tests.py:98`
> - insert — window end derived from the truncated start — `routes_tests.py:175`
> - insert — party-load read returns assignment rows — `routes_witness.py:127`
> - insert — submitted `blackout_days` accepted then discarded — `routes_witness.py:70`
> - insert — the invite gate is narrower than administrability — `routes_witness.py:140`
> - insert — decline / reinvite / waive gates and reasons — `routes_witness.py:227-293`
> - insert — start-FAT's three guards in order — `routes_tests.py:220`
> - insert — conclude requires a matching issued report — `routes_tests.py:254`
> - revise — FAIL cascade conditions — `routes_tests.py:254-307`
> - insert — abandon reason and the window guard's scope — `routes_tests.py:310`
>
> **§3.6 reports / labels**
> - insert — the above-zero bounds are `ERR_FIELD_VALUE_OUT_OF_RANGE` (making `SHORT_CIRCUIT` unreachable); DRAFT born with null `issued_at` and a verdict already computed — `routes_reports.py:61-81`
> - revise — issue-report: SoD id, skipped when `run_by_user_id` is null, and checked before parent state; parent-state id; five-field completeness list plus the impulse pair — `routes_reports.py:107-124`
> - insert — label creation: drawing scoped to the order (`ERR_DRAWING_NOT_FOUND`), report global, `ISSUED`/`PASS` enforced *at creation*, birth nulls — `routes_reports.py:152-183`
> - revise — generate: design-released gate; arc-energy computed before the staleness/report gates; drawing-status id; `generated_by_user_id` retained, not overwritten — `routes_reports.py:227-245`
> - insert — verify: header SoD before the body is read, body `verified_by_user_id` also policed, gate order; issue: cancelled/posture/freshness/ppe/duplicate ids — `routes_reports.py:252-289`
> - revise — void: `void_reason` mandatory, stale reason preserved unless empty, `CLEARED` *and* `STAGED` reverted unconditionally — `routes_reports.py:298-311`
>
> **§3.7 shipment / storage**
> - revise — stage creation: not-cancelled gate, share total checked *first*, dense-index rule, birth nulls — `routes_shipment.py:42-99`
> - insert — a cancelled stage's share is absorbed whole by the remainder holder — `calc.py:335-360`
> - revise — clear: gate order, `ERR_LABEL_STALE` ahead of `ERR_LABEL_NOT_ISSUED`, out-of-sequence id — `routes_shipment.py:120-140`
> - insert — storage creation gate order, staged-at comparison, eager pricing when `storage_end_at` is supplied, birth zeros — `routes_shipment.py:220-265`
> - revise — close: effective-end resolution (body → stored → now), agreement-state-first ordering, second granularity — `routes_shipment.py:284-303`
> - revise — waive records the *submitted* identifier and applies no stage-status gate — `routes_shipment.py:314-334`
> - revise — ship: blank `carrier_reference` → `ERR_MISSING_REQUIRED_FIELD` before the state gate; label and open-agreement gates; `billed_to_date_cents` is derived; deliver has no posture gate; order-cancel cascade covers `HELD`/`CLEARED`/`STAGED`/`SITE_STORAGE` — `routes_shipment.py:166-212`, `routes_orders.py:231-244`, `posture.py:110`
>
> **§3.8 commissioning**
> - insert — job creation examines only the order's cancellation; stage reference resolved globally; `energized_at` null — `routes_commissioning.py:56-82`
> - revise — mobilize gate list and the return-trip skips; energization's label-before-count ordering and fresh aggregates; energize re-tests the count and never completes the job — `routes_commissioning.py:104-173`
> - insert — punch creation requires only a non-terminal job; birth nulls — `routes_commissioning.py:226-251`
> - insert — assign error id; resolve imposes no job-state gate; body `closed_by_user_id` policed and recorded; reject reason with acting-only SoD — `routes_commissioning.py:272-350`
> - revise — demobilize reason/gates; cancel sources and the deliberate absence of an order gate — `routes_commissioning.py:176-218`
>
> **§3.9 warranty / supplier quality**
> - insert — suspect component resolved globally; duplicate check precedes the consequential check; claim birth fields — `routes_warranty.py:38-82`
> - insert — receive-unit gate; `ANALYSIS_IN_PROGRESS` is also a legal source for a further report; draft-exclusivity id; supplier reference and report birth nulls — `routes_warranty.py:129-231`
> - insert — publish: attribution-pair error ids and no order gate — `routes_warranty.py:266-282`
> - revise — settle: body identifier policed and recorded, credit recomputed before the cap test, `warranty_credit_total_cents` derived, stage rebill — `routes_warranty.py:141-170`, `posture.py:107`
> - revise — retract: blank-reason id, claim-state gate on the published path only, floored decrement, both arms zeroed, cross-claim quarantine survey — `routes_warranty.py:319-367`
> - insert — `event_count` bounds/default, `APPROVED`|`PROBATION` requirement, quality-summary read does not recompute — `routes_suppliers.py:106-117,144-148`
> - revise — suspend sources, `ERR_INVALID_STATE_TRANSITION` at or above 60.00, `suspension_reason` — `routes_suppliers.py:120-133`
>
> **§4 / §5**
> - §4 intro — revise — twenty resource families plus the clock family (was "twenty-one plus one") — `app.py:31-40`
> - §4 — revise — withdraw row now lists `ACCEPTED` plus its two extra guards — `routes_escalation.py:318-326`
> - §4 — revise — `/stage` row is `CLEARED` only — `routes_shipment.py:157`
> - §4 — revise — commissioning-job row: `DELIVERED` enforced at mobilize — `routes_commissioning.py:66`
> - §4 — revise — punch reject row bounces to `OPEN`, never `REJECTED` — `routes_commissioning.py:342`
> - §4 — revise — warranty-claim row: window tested at issue-rma — `routes_warranty.py:113`
> - §4 — revise — claim reject row: `SUBMITTED` or `NON_WARRANTABLE` only — `routes_warranty.py:180`
> - §5 — insert — the four framework-level ids outside the catalogue: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_REQUEST_INVALID` (framework status), `ERR_INTERNAL` 500 — `app.py:46-62`
>
> ## (c) Coverage
>
> Walked all 21 implementation modules: `app.py`, `clock.py`, `envelope.py`, `errors.py`, `store.py`, `validation.py`, `rbac.py`, `common.py`, `posture.py`, `calc.py` (16 named calculations) and all 11 `routes_*.py` blueprints. Machine-verified two closures: the §4 table and the implementation agree on all **127** method/path pairs exactly (no extras either way), and all **82** catalogued error ids match `errors.py` on both id and HTTP status. PRD was already uniquely pinned — no change needed — for the escalation six-step formula, the arc-flash energy/PPE/boundary/rating rules, the stage-billing waterfall arithmetic, the six-step storage fee, the punch aggregates and completion ratio, the warranty window and liability cap, the credit waterfall, the two supplier index variants, the posture reason-code catalogue, and the eight sites already pinned in `PRD_FINALIZED.md` (all re-verified as factually correct against the implementation and left untouched). No `test_helpers/` or `test_suite/` exist in the workspace; `SCAFFOLD*.yaml` and `worklog.md` were not read.

Orchestrator independently verified:
- Section-header lists **byte-identical** to `PRD_FINALIZED.md`; **127 endpoint rows** and **82 error rows** preserved; file ends on the same final catalogue row (no truncation); `diff` reports exactly **77 hunks**, matching the claim.
- **Implementation and tests are untouched** by Steps 8 and 9 (`find -newermt` after my verified sweep returns nothing), so the independently confirmed 96/96 × 8-round result still describes the code this PRD documents.
- Re-ran both of Step 9's "machine-verified closures" myself, from Flask's own `url_map` rather than from the agent's report:
  - **Closure 1 — endpoints: exact bijection.** 127 PRD §4 table pairs ↔ 127 registered routes, 0 PRD-only, 0 impl-only (after normalising path-parameter *names*, which differ cosmetically: the PRD writes `{id}` where the code uses `{oid}`, `{jid}`, etc.).
  - **Closure 2 — errors: exact match.** All 82 catalogued ids present in `errors.HTTP_STATUS`, **0 missing, 0 status mismatches, 0 impl-only**. The four framework ids Step 9 documented as sitting *outside* the catalogue (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_REQUEST_INVALID`, `ERR_INTERNAL`) are correctly absent from that table, confirming the §5 insert is accurate rather than contradictory.
- The `§4` family-count revision is a **genuine bug fix in the original PRD**, not a cosmetic reword. Flask registers **21 top-level path segments**, exactly one of which (`_clock`) is administrative → **20 resource families + 1 clock family**. `PRD.md` said "twenty-one sibling resource families plus one administrative clock family" (implying 22 segments) while its own §2.11 rungs 7-26 said "the twenty resource families" — the document contradicted itself, and Step 9 resolved it in the direction the code supports.

---

# PIPELINE COMPLETE — task_2200_transformer_switchgear_manufacturing — 2026-09-01T01:50:00.000Z

All 9 steps done. Final artifact inventory:

| artifact | size | status |
|---|---|---|
| `SCAFFOLD.yaml` | 5010 lines | §1.0-§1.7; 20 entities, 17 state machines, 5 concurrency rules, 16 calculations, 82 validations, 127 endpoints, 82 errors, 13 roles |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3440 lines | §1.8 queue A — 9 rules, 21 non-stub instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3071 lines | §1.9 queue B — 9 sections, 77 non-stub instances |
| `workspace/INSTRUCTION.md` | copied | shared implementer brief |
| `workspace/PRD.md` | 599 lines | generated from §1.0-§1.7 only; both design indices withheld |
| `test_helpers/` | 9 files, 2655 lines | fixtures, factories, per-role header builders, assertion library |
| `test_suite/` | 23 modules + conftest, 6301 lines | **96 tests**; queue A 21/21, queue B 75/77 |
| `workspace/implementation/` | 23 files, 5029 lines | Python + Flask, in-memory only, zero seeded rows |
| `workspace/PRD_FINALIZED.md` | 601 lines | +0.33% over PRD.md; 8 Step-7-traced sites pinned |
| `workspace/PRD_COMPLETED.md` | 601 lines, 174,629 chars | +30,320 chars over PRD_FINALIZED; 77 hunks; PRD/impl closure reached |

**Final test state: 96/96 passing in all 8 parallel rounds, confirmed across 3 consecutive independent sweeps (24 green rounds), the last run by the orchestrator.**

Benchmark contract invariants, all verified on the final artifacts:
- Zero seeded entities — a fresh boot returns `total_count=0` for all 14 top-level list families.
- Storage in-memory only — no sqlite/JSON/pickle/tmp writes anywhere in `implementation/`.
- No wall-clock reads outside `clock.py`; every temporal rule flows through the logical clock.
- No `skip`/`xfail` markers, and no error-id assertion downgraded to a status check.
- 0 tests deleted across the whole run; a single assertion removed under the partial-coverage rule.
- Every test carries exactly one `Design:` tag resolving to a real design-index instance.
- PRD-first isolation held: PRD generation never saw either design index, and the implementation agent confirmed it never read `test_suite/`/`test_helpers/` despite their appearing mid-session.

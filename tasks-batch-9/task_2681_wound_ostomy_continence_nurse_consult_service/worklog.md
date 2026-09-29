# Worklog — task_2681_wound_ostomy_continence_nurse_consult_service

## Step 1: Create task directory — 2026-09-04T05:46:03.307Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2681_wound_ostomy_continence_nurse_consult_service` and its `workspace/` subdirectory. Index 2681 was pre-assigned by the invoker; no auto-allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-04T07:36:16.558Z

All three scaffold artifacts are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2681_wound_ostomy_continence_nurse_consult_service/`

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | **3263** |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **1611** |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **5393** |

Top-level keys verified: `SCAFFOLD.yaml` carries neither design key; the other two carry exactly `scaffold_difficulty_design` / `scaffold_corner_design`.

## SCAFFOLD.yaml (§1.0–§1.7)
13 entities · 72 endpoints · 12 state machines / 62 transitions · 7 calculations · 34 validations · 46 error codes · 5 roles · 2 `concurrency_rules` · 14 global constants. Profile: `compliance_audit` + `quota_allocation`, `expert_plus`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
All 9 Difficulty Rules × 2 instances = **18**, e.g. dual-variant acuity (intake-provisional vs assessed-final), tiered per-day rental rounding + vendor fee keyed on the PRE-fee cost, the return/resubmit cycle, the 6-hop validate→HAPI→RCA→unit-posture→order-hold cascade, order-state-beats-budget and segregation-beats-POA-window priority pairs, the 70.0 P1 boundary, lapsed-nurse assignment block, reclean-buffer rental adjacency, and two conservation invariants (unit rental ledger, nurse consult load).

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
**98 instances = 74 authored + 24 `excluded_because` stubs**, across all nine guide sections (only guide-declared `claim_type` names used):
entities 13 · state_machines 22 · calculations 21 · validations 20 · endpoints 8 · **errors 4** · **rbac 4** · **cross_cutting_complexity_layers 5** · **consistency_model 1**.

Sections finished this session: the 404 family + the two 404-ordering rules (path-before-body, declared-field-order) + 401 unauthenticated; RBAC exclusive/shared denials for all five roles (including SystemOperator's empty `shared_operations` making even `GET /units` a 403, and the clock being refused to the director) plus the two segregation facets §1.9 hadn't taken (restage must be the original stager; RCA lead must not be); both OCC rules (stale patient version, stale unit version) rejected-then-accepted-after-reread; the cumulative posture ladder probed at counts 1/2/3/4 with the "3rd HAPI must not re-stamp the hold" no-change step; and one `immediate`-consistency instance asserting all cascade hops in the same response and the next read. Cascading-side-effects and dual-variant layers are stubs citing their §1.8 owners.

Coverage bookkeeping: **all 46 error codes are asserted in at least one authored recipe**; no duplicate `name` across the two design files; every stub cites an existing §1.8 instance and carries no `test_recipe`.

## Bugs found and fixed while cross-checking
- `SCAFFOLD.yaml` `Patient.admitted_at` demanded "three fractional digits" while every other datetime is plain ISO 8601 (and 100+ recipe payloads use second precision) → relaxed to second precision.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: `mrn: "MRN-A"` violated the 6–16 char rule → `MRN-A01`; invalid enums `anatomic_location: PERISTOMAL` → `OTHER`, `HEEL` → `HEEL_LEFT`, `surface_class: BARIATRIC` (×2) → `BARIATRIC_BED`.
- Earlier in the task: `escalation_reason` → `reason` on `/escalate`.
- Swept all payloads programmatically for enum membership, string-length/numeric ranges, per-setup natural-key collisions, and query-string params against declared `input:` (the linter strips query strings, so these are unlinted) — all clean afterwards.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1134

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-09-04T07:36:37.933Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T07:52:27.313Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **479 lines**, last heading `## 5. Error Code Catalogue`, final line is the `| \`ERR_RENTAL_BUDGET_EXCEEDED\` | 402 |` table row. Tail verified via `tail -30`: the file ends at a real section boundary, mid-table-completion, not mid-sentence. No audit footer, no sibling report files written.

**Sections covered**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 subsections (2.1 RBAC / principals, 2.2 Response Structure *verbatim from the skill contract file*, 2.3 Pagination, 2.4 Identity + timestamps + logical clock, 2.5 Path/reference resolution + referential coherence, 2.6 OCC on Patient and Unit parents, 2.7 Two-person clinical controls, 2.8 Precision/rounding/money, 2.9 Cascade discipline + derived counters, 2.10 the full normative validation ladder)
- §3 Business Logic — 9 subsections (units/rental ledger; patient admission and discharge; certification pipeline; consult lifecycle; bedside staging and dispute cycle; pressure-injury cases and RCA; prevalence/incidence survey programme; support surfaces and the two rental dimensions; formulary, dressing protocols, ostomy education)
- §4 Endpoint Definitions — 4-column table (Method | Path | Description | Authorized Role(s))
- §5 Error Code Catalogue — 2-column table (Error ID | HTTP Status Code)

**Coverage vs SCAFFOLD.yaml** (all verified programmatically)
- Entities 13/13; state machines 12/12 with all 62 transitions and every state name present
- Endpoints **72/72** — method+path pairs diffed against the scaffold: 0 missing, 0 extra
- Errors **46/46** in scaffold order, statuses exact; 0 codes used in prose that are absent from the catalogue, 0 catalogue codes never explained in prose
- Roles 5/5; concurrency rules 2/2; calculations 7/7; validation rungs 34/34 (every scaffold priority appears in the §2.10 ladder); all 14 global constants expressed as literal values in prose rather than symbolic names

**Hard Contract reports**

*Contract 1 — Field-Name Coverage: PASS.* 129 unique identifiers extracted from `entities[].fields[].name`, `request_body`, `input`, `query_params`, `path_params` (optional `?` markers stripped). All 129 appear verbatim in backticks in the PRD. Missing: 0. Note: the four calculation *labels* (`consult_acuity_score`, `unit_survey_metric`, `rental_cost_projection`, `dressing_protocol_weekly_cost`) are scaffold-internal names, not persisted fields; their output fields (`acuity_score`, `acuity_variant`, `last_prevalence_rate`/`last_incidence_rate`, `projected_cost_cents`/`actual_cost_cents`, `weekly_cost_cents`, `changes_per_week`) are all covered.

*Contract 2 — Rule Coverage: PASS.* All 34 validation rungs are stated in §2.10 in numeric priority order, each with its check, error id, HTTP status, and full `applies_to` endpoint enumeration, closing with the rung 12 / 20 / 58 tie-break note. Both OCC rules (`expected_patient_version` → `ERR_STALE_PATIENT_VERSION` 412, `expected_unit_version` → `ERR_STALE_UNIT_VERSION` 412) carry their occ_field, error, status, and the exclusivity statement. All 62 transitions, all 7 calculations (including the three dual-variant pairs and the three pinned evaluation orders: acuity rounds to 1 dp *before* clamping at 100; rental cost rounds half-up per-day *before* summing; vendor fee tier keyed on *pre-fee* `projected_cost_cents`), all cross-entity side effects (ledger encumber/commit/release, `active_consult_load` conservation, `survey_posture` ladder, `open_hapi_rca_count`, `pending_outpatient_followup_count`, `disputed_staging_count`, cascade versioning), field-level defaults, and sibling-branch symmetry (teach-back pass vs stay-at-`ACTIVE`; validate vs dispute vs restage; approve vs deny) are in prose. Three scaffold ambiguities were resolved toward the priority-ordered validations table and documented in prose: discharge blocked by a live rental order → `ERR_ORDER_NOT_PENDING`; `ERR_RCA_NOT_COMPLETE` scoped to the consult-close gate per priority 36; `ERR_OBSERVATION_OUTSIDE_WINDOW` follows priority 42 (`onset_at` ≤ `observed_at`), with the closed-window onset test expressed only as the incidence numerator filter.

*Contract 3 — §3 Path Purity: PASS.* 1133 backticked tokens in §3 scanned: 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path. §3 names operations exclusively by state-transition pair, role + gerund, or capability description. Paths appear only in §2.10 (explicitly permitted) and §4.

**Orchestrator truncation check (per invoker instruction):** independently verified — 479 lines, §4 contains exactly 72 endpoint rows, §5 contains exactly 46 `ERR_*` rows, file ends on a complete table row at a real section boundary. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T08:32:17.865158348Z

Implementation complete and smoke-verified.

## Modules (`.../task_2681_wound_ostomy_continence_nurse_consult_service/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `core.py` | 778 | 46-code error table + `ApiError`, Decimal/money helpers, canonical datetime layer, global constants, logical `Clock`, 13-store in-memory `Database`, envelope builders, auth rungs 1-2, declarative field validator (rung 3), pagination/filters/chrono ordering, `must()` 404 mapping, optimistic-concurrency checks |
| `calc.py` | 291 | all 7 calculations with pinned evaluation order |
| `services.py` | 477 | cross-aggregate side effects: unit ledger, posture derivation + order holds, 5-hop validate cascade, supersede/reclassify, HAPI close reversal, 6-hop cancel compensation (1,2,3,2b,2c,3b), surface occupancy + reclean buffer, survey-window capacity |
| `routes_org.py` | 323 | Unit, Patient, WocNurse — 15 endpoints |
| `routes_consult.py` | 262 | ConsultRequest — 10 endpoints |
| `routes_clinical.py` | 307 | SkinAssessment, PressureInjuryCase — 11 endpoints |
| `routes_survey.py` | 299 | SurveyRound, SurveyObservation + unit-report — 11 endpoints |
| `routes_rental.py` | 327 | SupportSurface, SupportSurfaceOrder — 12 endpoints |
| `routes_formulary.py` | 307 | FormularyProduct, DressingProtocol, OstomyEducationPlan — 12 endpoints |
| `app.py` | 107 | blueprint registration, Decimal-aware JSON provider, `/_clock/set_current_utc`, all error handlers |
| `start.sh` | 12 | guarded pip install + `exec python3 app.py` on `$PORT` (default 10000) |
| `requirements.txt` | 1 | Flask==3.0.3 |

3491 lines total. Every module compiles (`py_compile` clean).

## Coverage
- **Endpoints: 72/72.** Verified programmatically by diffing Flask's `url_map` against every `method`/`path` pair in SCAFFOLD.yaml — zero missing, zero extra.
- **Error codes: 46/46** wired (13 not-found codes are raised centrally through `must()`).
- 13 entities, 12 state dimensions (incl. the parallel `fulfillment_status` × `billing_status` on the order row), 7 calculations, 34 validations, both optimistic-concurrency parents, both dual-variant calculations, SoD triad, and the normative priority ladder.

## Smoke test (port 17681, killed by PID from `ss -ltnp`; port confirmed free)
Five scripted passes, ~160 assertions, all green:
1. Happy path end-to-end across all 13 entities. Spot-checked figures: rental 14d @12345 → projected 164192, fee 8210, authorized 172402; 8-day actual → 102402 with released 70000; acuity 63.3/P2 intake vs 95 assessed_final; eligibility 64.00; weekly protocol cost 7500.
2. Posture cascade: HAPI counter 1→OPEN, 2→RESTRICTED, 4→FROZEN, pending order picks up `requires_director_override` + `posture_hold_applied_at`, holds lift only when posture returns to OPEN.
3. Reclean buffer exact (`rental_end`+12h boundary blocks at 06:00, allows at 12:00), `ERR_RENTAL_BUDGET_EXCEEDED` 402, `ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION` 422, ladder-order probes (401 before 403 before 400 before 404).
4. Full 6-hop cancel compensation byte-exact: ENCUMBERED→RELEASED with fulfillment preserved, REQUESTED→DENIED with `CONSULT_CANCELLED`, protocol VOIDED, plan CLOSED_INCOMPLETE with cleared follow-up, patient counter decremented, nurse load released, ledger drained to cap.
5. Supersede/reclassify chain (prior case → RECLASSIFIED, counter decrement, `predecessor_case_id` linked), POA window closed at +24h, incidence window exclusion (onset before window excluded) and 33.33 rounding.

Fresh boot re-verified: logical clock reads exactly `2026-08-01T00:00:00.000Z` with no wall-clock fallback, and all 13 stores report `total_count: 0` — nothing seeded, in-memory only.

**One real bug found and fixed:** `POST /consult-requests/{id}/triage` computed acuity/band/SLA but never set `status := TRIAGED`, leaving the consult in REQUESTED. I also removed a non-contract convenience `GET /_clock/set_current_utc` so that path now correctly 405s.

# Unit test generation (Stage 1 + Stage 2)

`test_helpers/` (9 modules, 2485 lines) and `test_suite/` (`conftest.py` + `test_01` … `test_15`, 9897 lines) at the task root; nothing under `workspace/`.

**108 tests, every one carrying exactly one `Design:` tag as its final docstring line.** 36 queue-A tests covering all 18 §1.8 difficulty instances at 2 tests each; 72 queue-B tests covering 72 of the 74 authored §1.9 corner instances (24 §1.9 entries are stubs with `excluded_because` and were not translated).

Two authored corner instances skipped for non-unique-derivability — the PRD grounds no 400 for undeclared or server-owned body fields, so the asserted "client input ignored / rejected" outcome is not derivable:
- `entities/unit_system_fields_server_minted_client_input_ignored`
- `entities/support_surface_order_cost_fields_computed_client_input_ignored`

Assertions dropped inside otherwise-translated recipes, same reason: the future-`admitted_at` 400 in both RBAC clock recipes (§3.2 states the constraint but attaches no code, and rung 3 enumerates only schema conformance) — replaced by a `triaged_at` read, since §3.4 pins `triaged_at` to the logical clock; and the two-hops-in-one-request `PressureInjuryCase.version == 3` assertion in the cascade-visibility recipe.

Verification, all green: `py_compile` and `pyflakes` clean on every file; all 315 `PRD §` citations confirmed verbatim against `workspace/PRD.md` after whitespace normalisation; every `test_helpers` import resolved by live `hasattr`; every `api.<method>` name checked against `dir(ApiClient)`; all `Design:` tags checked against instance names mechanically extracted from both design yamls with their enclosing `rule_id`/`section`; no duplicate test names; no test missing the `api` fixture.

## Step 5: Generate Unit Tests — 2026-09-04T09:41:48.329937584Z

Generation is complete and fully verified.

## Output locations (task root, nothing under `workspace/`)
`/home/ubuntu/github/CodingPRD/tasks/task_2681_wound_ostomy_continence_nurse_consult_service/test_helpers/` and `.../test_suite/`. A stray scan of `workspace/` (which holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`) found no test dirs or test files; `__pycache__` dirs from the compile checks were removed.

## Per-file line counts
Helpers (2485 lines): `__init__.py` 37, `api_client.py` 336, `api_errors.py` 106, `assertions.py` 361, `constants.py` 101, `factories.py` 374, `fixtures.py` 652, `test_users.py` 60, `types.py` 458.

Suite (9897 lines): `conftest.py` 42, `test_01_unit_registration_and_ledger.py` 304, `test_02_patient_admission_and_lifecycle.py` 367, `test_03_consult_intake_and_acuity.py` 758, `test_04_consult_revision_and_escalation_cycles.py` 367, `test_05_nurse_certification_and_assignment.py` 765, `test_06_skin_assessment_validation.py` 1006, `test_07_hapi_cascade_and_posture.py` 1077, `test_08_rental_costing.py` 517, `test_09_rental_ledger_and_dimensions.py` 1020, `test_10_surface_availability.py` 382, `test_11_survey_rounds_and_windows.py` 706, `test_12_survey_metrics.py` 841, `test_13_formulary_and_protocols.py` 639, `test_14_ostomy_education.py` 220, `test_15_errors_and_rbac.py` 886.

## Tests emitted per queue
- **Queue A (Difficulty, §1.8): 36 tests** covering all 18 instances at 2 tests each.
- **Queue B (Corner, §1.9): 72 tests** covering 72 distinct instances. The yaml has 98 entries, 24 of which are stubs carrying `excluded_because`, so 74 were authored.
- **Total 108 tests.** Every test carries exactly one `Design:` line as the last line of its docstring, and every tag was checked against instance names extracted mechanically from both yamls together with the enclosing `rule_id` / `section` — zero mismatches, zero untagged, zero dual-tagged.

## Skipped instances (2, both non-unique-derivability)
- `Corner/entities/unit_system_fields_server_minted_client_input_ignored`
- `Corner/entities/support_surface_order_cost_fields_computed_client_input_ignored`

Both recipes assert that client-supplied values for server-owned/undeclared fields are rejected or silently ignored. The PRD grounds neither outcome: rung 3 enumerates only required-field, type, enum, numeric-range and string-length conformance, and no sentence says undeclared body members are ignored rather than refused, so neither branch is uniquely derivable. Nothing was weakened, marked xfail or stubbed.

Two assertions were also dropped from inside otherwise-fully-translated recipes for the same reason: the future-`admitted_at` 400 in both RBAC clock recipes (§3.2 states the constraint but attaches no error code) — replaced with a `triaged_at` read, since §3.4 pins `triaged_at` to the logical clock, which proves the clock position just as directly; and the `PressureInjuryCase.version == 3` two-hops-in-one-request assertion in the cascade-visibility recipe.

## Verification (all green)
`py_compile` and `pyflakes` clean on all 25 files (the only pyflakes output anywhere is the expected re-export noise in `test_helpers/__init__.py`). All 315 `PRD §` citations confirmed verbatim against `workspace/PRD.md` — two defects were found and fixed in this pass: one truncated sentence in `test_09` (extended to the full §3.8 settlement sentence) and one paraphrased §2.1 `UnitCharge` sentence in `test_15` ("own ward" → the PRD's "own unit"). Every `test_helpers` import resolves via live `hasattr` on the imported package; every `api.<method>` call name exists on `ApiClient` with a compatible signature; no duplicate test names within or across files; every test takes the `api` fixture; no generated comment mentions "scaffold".

## Step 7: Iterate Tests + Fixes — 2026-09-04

Three parallel 8-round sweeps (`--isolation per-test-server`, 108 tests/round). Final sweep: **all 8 rounds 108/108 passed, 0 failed, 0 errors, 0 skipped** (~193s per round). Failure counts by iteration: 13 → 1 → 0. Every failure was deterministic across all 8 rounds — no flakiness was observed at any point.

**No tests deleted.** Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so all 13 went to STEP 2/STEP 3 rather than to deletion.

### Fixes to `test_suite/`
- `test_06_skin_assessment_validation.py`, `test_the_poa_window_edge_is_inclusive_and_the_gate_reads_the_payload` — moved `set_clock("2026-08-03T00:00:00Z")` ahead of both `create_patient` calls. The fixture admitted `edge_patient` at `2026-08-02` while the clock still read its default `2026-08-01`, which PRD §3.2 ("must not be later than the logical clock at the moment of admission") correctly refuses with `ERR_INVALID_REQUEST`. Test setup bug, not an implementation defect; the PRD-required admission-window check was left intact.

### Fixes to `implementation/`
- `core.py`, `new_id()` — was minting `"<prefix>_<uuid4hex>"`. PRD §2.4: "Every resource carries an `id` that is a server-minted UUID string with no type prefix of any kind". Now returns `str(uuid.uuid4())`. This single fix cleared 10 of the 13 failures (unit, patient, nurse, consult, product, protocol, plan and observation ids). Nothing in the codebase parsed the prefix, so the change was contained.
- `routes_rental.py`, `create_order()` — `requires_director_override` was hardcoded `False` at creation, with a comment asserting the flag is only ever raised by validate-cascade hop 5. PRD §3.8 says otherwise: "when the posture is `RESTRICTED` at creation time the order is created with `requires_director_override` already true." Now derived from the unit's live `survey_posture`. `posture_hold_applied_at` is deliberately left null on this path — §3.8 stamps only the override flag at creation, and §3.5 stamps the instant only in hop 5.
- `routes_survey.py`, `create_observation()` — `new_row()` unconditionally attaches `version` and `updated_at`, but PRD §2.4 carves out the one exception: "a survey observation is an immutable audit record and carries only `id` and `created_at` — it has neither `updated_at` nor `version`". Both keys are now popped before insert. Verified no code path bumps an observation and that `chrono()` orders on `created_at`/`_seq` only.

Storage remains in-memory dicts only; no seeding, no on-disk persistence.

## Step 7: Run Tests and Iterate (orchestrator record of subagent's returned summary) — 2026-09-04T10:13:06.423184266Z

Loop complete — the task now passes a fully clean 8-round parallel sweep.

## Result

**3 iterations.** Failure counts: 13 → 1 → **0**. Final sweep: all 8 parallel rounds **108/108 passed**, 0 failed, 0 errors, 0 skipped (~193s per round).

Every failure was deterministic — identical in all 8 rounds of every sweep. **No flakiness was observed at any point**, so no load-induced false positives had to be filtered out.

## Tests deleted: none

All 13 failing assertions traced to verbatim PRD sentences and were uniquely derivable, so every one went to STEP 2/STEP 3 rather than deletion. No assertion was weakened, and no `skip`/`xfail` was added.

## Fixes to `test_suite/` (1)

- **`test_06_skin_assessment_validation.py`** → `test_the_poa_window_edge_is_inclusive_and_the_gate_reads_the_payload`: moved `set_clock("2026-08-03T00:00:00Z")` ahead of both `create_patient` calls. The setup admitted `edge_patient` at `2026-08-02` while the clock still read its default `2026-08-01`, which PRD §3.2 ("must not be later than the logical clock at the moment of admission") correctly refuses. A test-ordering bug — the PRD-required admission-window check in the implementation was left intact.

## Fixes to `implementation/` (3)

- **`core.py` → `new_id()`**: was minting `"<prefix>_<uuid4hex>"`; PRD §2.4 requires "a server-minted UUID string with **no type prefix of any kind**". Now `str(uuid.uuid4())`. This one fix cleared **10 of the 13** failures across unit, patient, nurse, consult, product, protocol, plan and observation ids. Nothing parsed the prefix, so the change was contained.
- **`routes_rental.py` → `create_order()`**: `requires_director_override` was hardcoded `False`, with a code comment explicitly denying the rule. PRD §3.8: "when the posture is `RESTRICTED` at creation time the order is created with `requires_director_override` already true." Now derived from the unit's live `survey_posture`. `posture_hold_applied_at` is deliberately still null here — §3.8 stamps only the flag at creation; §3.5 stamps the instant only in cascade hop 5.
- **`routes_survey.py` → `create_observation()`**: the shared `new_row()` helper unconditionally attaches `version` and `updated_at`, but PRD §2.4 carves out the one exception — a survey observation "carries only `id` and `created_at` — it has neither `updated_at` nor `version`". Both keys are now popped before insert. Verified no path bumps an observation and that `chrono()` orders on `created_at`/`_seq` only.

Notable: the two non-id bugs were both cases where the implementation had encoded an assumption *contrary* to an explicit PRD sentence — one in a code comment ("only raised when the posture *becomes* RESTRICTED"), one by inheriting a generic row helper past a documented exception. Storage remains in-memory dicts only, with no seeding or on-disk persistence.

**Orchestrator verification:** independently confirmed all 8 `results.{1..8}.json` exist (written 10:02) and each reports `passed=108, failed=0, errors=0, skipped=0, total=108`. Step 8 is NOT skipped (1 test_suite fix + 3 implementation fixes).

## Step 8: Finalize PRD — 2026-09-04T10:21:45.268407119Z

Done.

## Line counts
- `PRD.md`: 479 lines — `PRD_FINALIZED.md`: 479 lines (0.0% line delta; 2 lines revised in place, +191 chars total, no new sections)

## Changes (2)
- **§2.4 Resource Identity, Timestamps and the Logical Clock** — revise — added "in the canonical hyphenated 36-character form" to the `id` sentence, which previously said only "a server-minted UUID string with no type prefix of any kind" — `implementation/core.py:381-384` (`new_id` → `str(uuid.uuid4())`)
- **§3.8 Requesting a rental** — insert — one sentence pinning that a newly created order's `posture_hold_applied_at` is null regardless of posture, and that only the §3.5 cascade writes that instant — `implementation/routes_rental.py:168-169`

## Per-edit pre-edit search log

**Edit 1 — §2.4 `id` format**
- (a) Subject: how resource `id` values are minted and rendered.
- (b) Enumerated/read: `core.py:381` `new_id()` (sole minter, `str(uuid.uuid4())`); `core.py:396-406` `new_row()` (only caller of `new_id`); grepped all 17 `new_row(`/`new_id(` callsites plus every `"id"` assignment across `app.py calc.py core.py routes_*.py services.py` — no row is inserted with a hand-built id, and `core.py:758` `insert()` keys off `row["id"]` without parsing it. Also checked `core.py:412-416` `_request_id()`, which mints the envelope's `api_request_id` with a `req_` prefix — that is a `meta` field, not a resource `id`, and is separately specified in PRD §2.2 line 48, so the "no type prefix" claim is not widened onto it. Confirmed nothing anywhere parses or splits an id.
- (c) Adjustment: kept the original clause verbatim and inserted the form phrase as a subordinate clause rather than rewriting the sentence, so the existing "no type prefix of any kind" wording (which Step 7 cited verbatim) is untouched. Deliberately did not claim uniqueness/monotonicity or say "v4", since the PRD's consumers only need the wire form.

**Edit 2 — §3.8 `posture_hold_applied_at` at creation**
- (a) Subject: the initial and subsequent values of `posture_hold_applied_at` on a rental order, and the coupled `requires_director_override` flag.
- (b) Enumerated/read: grepped `posture_hold_applied_at|requires_director_override` across all impl files → exactly four write sites. `routes_rental.py:149-172` `create_order()` (flag derived from `unit["survey_posture"] == "RESTRICTED"`, instant `None`); `services.py:75-85` `hold_requested_orders()` (cascade hop 5 — sets flag true and stamps the instant with `now()`, only for `REQUESTED` orders on the unit); `services.py:88-97` `lift_requested_order_holds()` (RCA-closure compensation — resets flag to false and clears the instant to null); `routes_rental.py:224` `approve_order()` (read-only consumer of the flag). Also read the hop-4/hop-5 guard at `services.py:270-278` (`current != previous and current in ("RESTRICTED","FROZEN")`) and the supersession-reversal path at `services.py:321` (`apply_posture` with **no** hold lift), and cross-checked both against PRD §3.5 line 253, §3.6 line 273 and §2.9 line 124 — the existing PRD prose already matches those three paths, so no further edit was needed there.
- (c) Adjustment: first drafted "…is stamped only by the §3.5 cascade", which would have read as a universal claim over *all* writes to the field and thus mis-described `lift_requested_order_holds()` clearing it to null. Re-scoped to "that **instant** is written **solely** by the posture cascade of §3.5" — clearing to null is not writing an instant — and added "regardless of the unit's posture" so the sentence also covers the `OPEN`-posture creation path, not just the `RESTRICTED` one it is appended to.

## Items that needed no PRD edit
- `core.py new_id()` prefix removal — §2.4's "with no type prefix of any kind" was already verbatim and uniquely determining; only the wire *form* was open (Edit 1).
- `routes_rental.py create_order()` `requires_director_override` — §3.8 line 305 already states the rule verbatim; the impl had encoded the opposite. Pure impl-vs-PRD mismatch, no PRD silence. Only the silent companion field was pinned (Edit 2).
- `routes_survey.py create_observation()` dropping `version`/`updated_at` — §2.4 line 86 *and* §3.7 line 285 both already carve out the survey-observation exception explicitly. Verified no impl path bumps an observation and that `chrono()` (`core.py:700`) orders on `created_at`/`_seq` only.
- `test_06` clock-ordering fix — pure fixture/ordering bug; §3.2 line 183 already requires `admitted_at` to be no later than the logical clock, which is what the implementation enforces.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly the two described in-place line revisions (lines 84 and 305), no other hunks, both files 479 lines, +238 bytes. No truncation.

## Step 9: Complete PRD — 2026-09-04T11:00:37.236638598Z

Run as **three sequential file-partitioned passes** over `implementation/` (a single-pass scan has historically no-op'd and produced a byte-identical PRD_COMPLETED.md; partitioning forces each module set to be walked). Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes B and C edited it in place.

### Pass A — core.py, calc.py, app.py
479 → 480 lines, 105,417 → 110,683 chars (+5,266). 15 hunks / 16 pinned behaviors: **11 ambiguity-pins, 5 mismatch-revisions**. core.py `ERROR_HTTP` cross-checked against §5: 46/46 codes, identical statuses and order — no change needed.
- §2.1 — revise — ambiguity — empty/whitespace-only `X-User-ID` counts as absent (401); value trimmed, role matched case-sensitively — core.py:463-471
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 random lowercase alphanumerics — core.py:412-416
- §2.2 — revise — ambiguity — `api_request_timestamp` stamped from real host time, not the logical clock — core.py:419-421
- §2.2 — insert — mismatch — transport-level failures use the error envelope with `ERR_INVALID_REQUEST` at 404/405/500 (contradicting §5's flat 400); trailing-slash equivalence; `Content-Type` not inspected; absent/empty body read as `{}`; non-object JSON → 400 — app.py:40,66-96; core.py:485-496
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → 400; declared filter empty or off-enum → 400; undeclared query parameters ignored — core.py:648-684
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order, never by `id` — core.py:700-703
- §2.4 — revise — ambiguity — full accepted datetime grammar (optional seconds/fraction, `T` or space, `Z`/offset/no designator = UTC), UTC conversion, canonical echo, sub-ms truncation — core.py:213-261
- §2.4 — revise — ambiguity — clock repositionable repeatedly, forward or backward; `current_utc` echoed canonically — core.py:309-328
- §2.6 — insert — ambiguity — `expected_*_version` are non-negative integers compared by integer equality; missing/null/non-integer/negative → 400 before any 412 — core.py:769-780
- §2.8 — insert — ambiguity — pinned scales are arithmetic, not wire format: integral decimals serialize bare, `12.50` → `12.5`, never strings — app.py:24-34
- §2.10 rung 3 — insert — ambiguity — booleans never valid for numeric fields; integer fields accept integral JSON numbers; `min_len` measured on stripped value, `max_len` on raw; undeclared body members ignored — core.py:520-637
- §3.3 — revise — ambiguity — `last_competency_signoff_at` later than the clock yields month count 0 (never negative) — calc.py:257-262
- §3.5 — revise — mismatch — `measured_area_cm2` has no one-decimal enforcement; only 0..500 range checked — core.py:532-548
- §3.5 — revise — mismatch — POA candidate ordering: insertion order is the final key, `created_at` is not the sole tie-break — calc.py:209-212
- §3.8 — revise — mismatch — `billable_days` counts whole elapsed hours, floored at 1 (plain ceil would give 0 for a sub-hour span) — calc.py:136-140
- §3.9 — revise — mismatch — blank/over-long `justification` fails rung 3 with `ERR_INVALID_REQUEST`; only absence/explicit null reaches the 422 — core.py:523-528, routes_formulary.py:132,152-154
- Dead code noted (no PRD change): `core.money_out`, `core.score_out`, `calc.poa_window_open` are never called.

### Pass B — services.py, routes_org.py, routes_consult.py
480 lines / 110,683 → 115,903 chars (+5,220), no new lines or sections. **18 ambiguity-pins, 4 mismatch-revisions.**
- §2.10 rung 3 — revise — ambiguity — "Four conventions" → "Five"; explicit `null` on an optional field is a 400 unless that field's narrative allows null — core.py:554
- §2.10 rung 17 — revise — mismatch — discharge sub-rule added (no `APPROVED`/`DELIVERED` rental order) and `POST /patients/{patient_id}/discharge` added to the `ERR_RESOURCE_NOT_ACTIVE` list — routes_org.py:188-193
- §3.1 — insert — ambiguity — `unit_code` charset violation is a rung-3 400 checked before any collision lookup — routes_org.py:73-77
- §3.1 — insert — ambiguity — `rental_budget_cap_cents` upper bound 1,000,000,000,000 — routes_org.py:71
- §3.1 — insert — ambiguity — budget `delta_cents` bounds ±10^12; `reason` 1–2000 chars, not persisted — routes_org.py:110-113
- §3.2 — insert — ambiguity — post-dated `admitted_at` is a 400 checked before `unit_id` resolves, so it beats the 404 — routes_org.py:142-144
- §3.2 — insert — ambiguity — `discharged_at < admitted_at` is a 400 evaluated after both discharge conflict checks, inverting the usual ladder — routes_org.py:186-195
- §3.2 — revise — mismatch — live-rental discharge block raises `ERR_RESOURCE_NOT_ACTIVE`, not `ERR_ORDER_NOT_PENDING` — routes_org.py:192
- §3.3 — insert — ambiguity — opening nurse record shape (counters 0; three fields null) — routes_org.py:214-227
- §3.3 — revise — mismatch — a signoff re-derives `last_competency_signoff_at` across the whole history rather than overwriting it, so a later-filed earlier-dated signoff never wins — services.py:113-124
- §3.3 — insert — ambiguity — `competency_domain` 1–120 chars; `signed_off_at` unbounded against the clock — routes_org.py:251-254
- §3.3 — insert — ambiguity — the signoff is not an addressable resource; 200 with the nurse, not 201 — routes_org.py:257-267
- §3.3 — insert — ambiguity — `advance` takes no payload; `cert_expires_at` stored as supplied with no future requirement — routes_org.py:273,290
- §3.3 — revise — mismatch — lapse `reason` is validated (1–2000) but written nowhere; `cert_expires_at` survives a lapse — routes_org.py:314-321
- §3.4 — insert — ambiguity — return also clears `acuity_variant` and `triaged_at`; its `reason` is 1–2000 and unpersisted — routes_consult.py:142-149
- §3.4 — insert — ambiguity — neither assignment leg touches `escalation_count`, `triaged_at`, acuity, band or `sla_due_at` — routes_consult.py:202-204
- §3.4 — insert — ambiguity — escalation leaves `sla_due_at` untouched, so a re-assigned late consult is immediately re-escalatable and `escalation_count` accumulates; `reason` unpersisted — routes_consult.py:211-219
- §3.4 — insert — ambiguity — `closing_summary` 1–2000 chars; cancel `reason` 1–2000 and unpersisted — routes_consult.py:228,257
- §3.4 — insert — ambiguity — an order touched on both dimensions by the cancel cascade is versioned exactly once — services.py:374-384
- §3.4 — insert — ambiguity — a cancelled plan keeps `supply_transition_status`; nothing outside the six hops moves — services.py:404-425
- §3.5 — insert — ambiguity — validation never moves the consult's `status`; hops 2 and 3 are distinct writes, so a case landing at `RCA_REQUIRED` has its `version` raised twice — services.py:250-268
- §3.5 — insert — mismatch-adjacent — the reclassification reversal stops at the unit and never lifts order holds; with several reclassified cases the successor's `predecessor_case_id` names the most recently created — services.py:316-323
- §3.6 — revise — ambiguity — `predecessor_case_id` set only when the superseded row was `VALIDATED` and its case was actually reclassified, else null — services.py:304-315
- §3.6 — insert — ambiguity — a fresh case has four null fields but `contributing_factors` an empty array — services.py:201-216

### Pass C — routes_clinical.py, routes_survey.py, routes_rental.py, routes_formulary.py
480 lines / 115,903 → 126,830 chars (+10,927), all in-paragraph. 33 patches: **28 ambiguity-pins, 5 mismatch-revisions.** Every non-obvious claim was verified empirically against a live `app.test_client()` probe before being written.
- §3.5 — revise — mismatch — corrected Pass A's claim that `measured_area_cm2` accepts a JSON string: it must arrive as a JSON number, `"12.5"` fails rung 3 with `ERR_INVALID_REQUEST` (no field uses `decimal_str`). The one place an earlier pass's sentence was overridden; consistent with Pass A's own §2.2 "decimals are never emitted as JSON strings".
- §3.6 — revise — mismatch — case-closure posture lift requires the posture to have *moved* to `OPEN`; a closure on an already-`OPEN` unit lifts nothing even with a stale hold — services.py:339
- §3.8 — revise — mismatch — surface occupation marks are last-write-wins per approval/return call, not "the driving order chosen by the latest `created_at`" — services.py:173,180 via routes_rental.py:241,304
- §3.8 — revise — mismatch — reconcile does not check `fulfillment_status == RETURNED`; billing is the only precondition, and the asset returns to `AVAILABLE` only while still `CLEANING` with a reached `available_from` — routes_rental.py:315,320
- §3.9 — revise — mismatch — plan listing carries a fourth filter `supply_transition_status` — routes_formulary.py:254
- §2.10 rung 13 — insert — ambiguity — `/return` additionally requires `ENCUMBERED` billing after its rung-12 check — routes_rental.py:285
- §2.10 rung 64 — insert — ambiguity — rung covers `/sessions` (requires `ACTIVE`) and `/transition-supplies` (requires `TEACH_BACK_PASSED`), state before appointment — routes_formulary.py:274,290
- §3.5 — insert — ambiguity — `observed_at` range failures are 400s evaluated last, after both 404s, the link check, consult/patient state and even the 412 — routes_clinical.py:82
- §3.5 — insert — ambiguity — `staged_by_nurse_id` is a declared optional id: null/non-string is a 400 before the value is discarded — routes_clinical.py:70
- §3.5 — insert — ambiguity — the hop-1 patient write fires on every `POA` verdict, versioning the patient even when the flag already read true — services.py:242-247
- §3.5 — insert — ambiguity — `dispute_reason` required, 1–2000 chars, stored — routes_clinical.py:173
- §3.5 — insert — ambiguity — restaging recomputes nothing: acuity/variant/band/`sla_due_at` unchanged, patient not versioned, `disputed_staging_count` not wound back — routes_clinical.py:208-218
- §3.6 — insert — ambiguity — rca-start touches only the case row — routes_clinical.py:262-265
- §3.6 — insert — ambiguity — non-lead rca-complete is `ERR_UNAUTHORIZED` (403) checked after the `RCA_IN_PROGRESS` gate; the 6-entry `contributing_factors` ceiling is a 400 before `case_id` resolves — routes_clinical.py:276-283
- §3.6 — insert — ambiguity — `closure_note` required 1–2000, validated but not stored — routes_clinical.py:294
- §3.7 — insert — ambiguity — >20 ids, duplicate ids and a reversed window are 400s preceding unit resolution; element order preserved — routes_survey.py:57-65
- §3.7 — insert — ambiguity — every conditional-shape rule on an observation is a 400 evaluated before the four reference 404s; `at_risk: null` fails rather than defaulting — routes_survey.py:213,220-232
- §3.7 — insert — ambiguity — `unit_rows` follows `participating_unit_ids` order, includes zero-count units, computed on demand and mutates nothing — routes_survey.py:166-194
- §3.7 — insert — ambiguity — round `cancel` reason required 1–2000 and discarded — routes_survey.py:157
- §3.8 — insert — ambiguity — retire `reason` required 1–2000 and discarded; asset status checked before the live-order scan, both grounds share `ERR_RESOURCE_NOT_ACTIVE` — routes_rental.py:98-108
- §3.8 — insert — ambiguity — Pass B's hand-off: `consult_request_id: null` expressly allowed and stored null; a non-null value resolves after the other three references — routes_rental.py:127,135
- §3.8 — insert — ambiguity — `rental_end <= rental_start` is a 400 before reference resolution; a new order opens with four null fields — routes_rental.py:129,162-171
- §3.8 — insert — ambiguity — approval gates run in ladder order (state → version → occupation → FROZEN → missing override → day ceiling → budget), not narration order — routes_rental.py:209-233
- §3.8 — insert — ambiguity — `denial_reason` required 1–2000 and, unlike other reason fields, stored — routes_rental.py:250-256
- §3.8 — insert — ambiguity — delivery moves nothing outside the order row; `delivered_at` has a lower bound only, checked after the state gate — routes_rental.py:269
- §3.8 — insert — ambiguity — return requires `ENCUMBERED` billing after the `DELIVERED` check, with the datetime 400 after both — routes_rental.py:283-288
- §3.8 — insert — ambiguity — return leaves `billable_days`, `projected_cost_cents`, `vendor_service_fee_cents`, `authorized_cost_cents` at creation values; only `actual_cost_cents` is written — routes_rental.py:292-296
- §3.9 — insert — ambiguity — archive `reason` required 1–2000 and discarded; a second archive is `ERR_RESOURCE_NOT_ACTIVE` — routes_formulary.py:102-105
- §3.9 — insert — ambiguity — "latest assessment" tie-break is insertion order; a consult with no assessment fails the same gate — routes_formulary.py:115-121,146
- §3.9 — insert — ambiguity — on-formulary `justification: null` accepted and stored null; the same null on `NON_FORMULARY` is the 422 — routes_formulary.py:132,152
- §3.9 — insert — ambiguity — `ostomy_present` checked before `consult_type`; multiple independent plans per consult permitted — routes_formulary.py:226-231
- §3.9 — insert — ambiguity — sessions require `ACTIVE` (else `ERR_OSTOMY_PLAN_NOT_ELIGIBLE`); a session is not addressable, so 200 with the plan, versioning only the plan — routes_formulary.py:274-282
- §3.9 — insert — ambiguity — transition state failure carries `ERR_OSTOMY_PLAN_NOT_ELIGIBLE`, checked before the future-appointment rule — routes_formulary.py:290-295
- §3.9 — insert — ambiguity — the transition costs exactly one plan version across both advances and one patient version — routes_formulary.py:296-306

### Totals and orchestrator verification
PRD_FINALIZED.md 479 lines / 105,417 chars → **PRD_COMPLETED.md 480 lines / 126,830 chars** (+21,413 chars, +20.3%; 117 changed diff lines). Across the three passes: **57 ambiguity-pins, 14 mismatch-revisions** (one of which corrected an earlier pass).

Independently verified by the orchestrator: PRD_COMPLETED.md is **not** byte-identical to PRD_FINALIZED.md (117 diff lines, so the scan genuinely ran); §4 still lists 72 endpoint rows; §5 still lists 46 `ERR_*` rows; the file ends on the complete final catalogue row `| \`ERR_RENTAL_BUDGET_EXCEEDED\` | 402 |` at a real section boundary; 27 headings intact. `implementation/` was untouched by Step 9 (all module mtimes predate the 10:02 passing sweep), so the 8× 108/108 sweep evidence in `results.{1..8}.json` remains valid. Stray `__pycache__` directories left by the Pass C probe were removed.

## Pipeline complete
Steps 1–9 all finished. Final state: 108 tests, 8/8 sweep rounds green at 108/108; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md.

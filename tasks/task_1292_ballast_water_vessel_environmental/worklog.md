# Worklog — task_1292_ballast_water_vessel_environmental

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

Pre-assigned directory `tasks/task_1292_ballast_water_vessel_environmental/` with `workspace/` already created. Skipped per instructions.

## Resume Assessment — 2026-08-12T19:40:00.000Z

RESUME RUN. Prior run terminated mid-Step-2. Directory contained: `SCAFFOLD.yaml` (2061 lines, 84KB) + `worklog.md` + empty `workspace/`. Missing: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`.

`SCAFFOLD.yaml` was syntactically invalid (PyYAML rejects bare `token?` optional-param markers inside flow sequences — 19 occurrences, all on endpoint `input:` lines). Orchestrator applied a mechanical repair (wrapped each bare `token?` in double quotes; no semantic change) and re-validated: parses cleanly, all §1.1–§1.7 top-level sections present (entities:14, state_machines:9, concurrency_rules:3, calculations:7, validations:18, endpoints:52, errors:20, roles:5), no forbidden `scaffold_difficulty_design`/`scaffold_corner_design` keys, file ends cleanly inside the roles section. SCAFFOLD.yaml treated as COMPLETE and reused. Resuming Step 2 with generation of the two missing design-index files only.

## Step 3: Copy Shared Files — 2026-08-12T19:38:51.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1292_ballast_water_vessel_environmental/workspace/INSTRUCTION.md` (1424 bytes). Done out of order while the Step 2 design-index subagent runs; no dependency conflict.

## Step 2 (remainder): Generate Design Indices — 2026-08-12T20:28:02.000Z

Done. Both design artifacts were derived from the existing `SCAFFOLD.yaml` (untouched) and written, validated, and lint-checked.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1292_ballast_water_vessel_environmental/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1831 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1292_ballast_water_vessel_environmental/SCAFFOLD_CORNER_DESIGN.yaml` — 2497 lines, single top-level key `scaffold_corner_design`

Both parse with `yaml.safe_load`. The bare-bracket/`?` YAML pitfalls were handled by quoting all `$.data[N].field` capture paths and all bracketed `grounds:` entries (e.g. `"validations[priority=7]"`).

**Instance counts**
- §1.8 (27 instances, all with full structured `setup_api_calls`/`trigger`/`assert` chains): dual_variant_calc 2, combinatorial_formula 3 (one per mode a/b/c), non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 4, resource_temporal_overlap 3, compensating_invariant 3.
- §1.9 (84 entries = 63 active + 21 `excluded_because` stubs): entities 10, state_machines 15+4, calculations 7+6, validations 12+2, endpoints 5, errors 1+5, rbac 7+1, cross_cutting_layers 5+3, consistency_model 1.
- 111 unique instance names across the union; placeholder closure verified programmatically (every `${var}` bound by an earlier `captures:` in the same instance); every stub resolves to a real §1.8 instance name.

**Lint verdict**: `scaffold_lint.py` reports **zero violations in checks (a)–(e) across all 864 calls** in my design files. The only findings are 20 `(f) FK_REVERSE_UNREACHABLE` violations, which I confirmed fire with *empty* design files — they are pre-existing in the untouched `SCAFFOLD.yaml`: the linter's check (f) builds sub-resource prefixes with the literal placeholder `{id}`, while the scaffold declares nested routes with named placeholders (`{vessel_id}` etc.), so the scaffold's existing `GET /vessels/{vessel_id}/plans`-style reverse GETs (which satisfy the rule's intent) don't string-match. Since SCAFFOLD.yaml was off-limits, these stand as a scaffold↔linter placeholder-naming mismatch, not a defect in the design files.

**Difficulty profile encoded**: Harder-than-expert, exploiting the scaffold's compliance/audit DNA — dual-variant determinations (provisional INSUFFICIENT_DATA vs final TREATMENT_COMPLIANT on identical event streams) and statutory-vs-internal sampling thresholds; combinatorial edges in all three modes (scrubber branch nesting with 4.9%/0-ECA-hour inputs, per-event 3dp half-up rounding pinned to the 200.002 literal, and the circular severity↔posture dependency resolved by posture-at-detection yielding exactly score 40 = MAJOR); parallel voyage state axes asserted mid-drift (IN_PROGRESS × OVERDUE, COMPLIANT × OVERDUE), an inspection reopen cycle re-opening closed records, and a report-reject reporting-axis revert; a clock-driven depth-3 cascade (OVERDUE → ESCALATED → EnforcementCase → vessel posture) versus a depth-2 verify→rollup posture lift; three distinct validation-priority collisions (auth-vs-SoD, temporal-vs-fiscal, existence-vs-state); four inclusive/exclusive boundaries (organism 10.0, sulfur 0.10%, exchange 200.0 nm, zero tank balance); four cross-entity gates (Voyage→Plan, RecordBook→Voyage, EnforcementCase→NoncomplianceRecord, Inspection→NoncomplianceRecord); three temporal-window geometries (±6h buffered containment, 90-day closed appeal window, strict-greater overdue crossing) plus a 24-hour CRITICAL-escalation boundary built on an 80-point severity stack; and three conserved quantities (per-tank zero balance, discharged-volume partition across recompute, vessel clearance across escalate/close). All time-driven behavior is clock-pinned with literal timestamps, and all OCC tests use `${var}`-captured versions per §1.2.1.

## Step 4: Generate PRD — 2026-08-12T20:35:30.000Z

PRD generated and all three hard contracts pass.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1292_ballast_water_vessel_environmental/workspace/PRD.md`
**Line count:** 276

**Section list:**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Hierarchical Path Validation and Nested Resource Retrieval
  - 2.6 Precision, Rounding, and Timestamp Conventions
  - 2.7 Optimistic Concurrency Control
  - 2.8 Vessel Compliance Posture as a Cross-Cutting Gate
  - 2.9 Segregation of Duties
  - 2.10 Validation Priority Ordering
- 3. Business Logic & Workflows (12 subsections: Vessel Registration & BWMP; Voyage Lifecycle & Ballast Water Events; Exchange-Versus-Treatment Determination; Reporting Obligations; Sampling/Inspection; PSC Deficiency Rectification; Record Books; Emissions/Fuel Sulfur; Crew Drills; Noncompliance Response & Escalation; Enforcement Cases; Logical Clock)
- 4. Endpoint Definitions (4-column table, 52 endpoints)
- 5. Error Code Catalogue (2-column table, 20 error IDs)

**Coverage audit (Hard Contracts):**

```
Contract 1 — Field-Name Coverage:
- entities[].fields: 102 required, 102 present, 0 missing
- common fields (id/created_at/updated_at/version): 4 required, 4 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params (limit/offset): 2 required, 2 present, 0 missing
- endpoints[].path_params: 10 required, 10 present, 0 missing
Status: PASS

Contract 2 — Rule Coverage (probe-based):
- validations[] with priority: ordering expressed in §2.10 (18 validation rules each named in prose near their workflow, paired with error_id and status)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (expected_vessel_version / expected_voyage_version / expected_deficiency_version each named with ERR_STALE_VERSION + HTTP 412)
- state_machines[].transitions: all 26 transitions across 9 state machines expressed (from/to states, preconditions, side effects)
- calculations[]: all 7 expressed (exchange_vs_treatment, report_due_at, sampling_exceedance_threshold with internal-stricter variant, rectification_deadline, sulfur_compliance with BIOFUEL_BLEND variant, noncompliance_severity_derivation, voyage_compliance_posture_rollup) — 73/73 key-phrase probes present
- validations[] conditions: 18 checked, all matchable to error_id in prose
- endpoints[].side_effects / applies_to: expressed in workflow narratives
- entities[].fields[] structured content: defaults (flag_state=US, hold_flag=false), conditionally-required fields, and enum sets all transcribed
- sibling-branch symmetry: parallel branches (treatment/exchange attribution; A10–A99 deadlines; ECA/non-ECA sulfur; drill recurrences) rendered with equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned: 508
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 20 scaffold error IDs appear backticked in prose (trigger conditions live in §2/§3; §5 carries only ID + HTTP status).

## Step 6: Generate Implementation — 2026-08-12T21:06:56.000Z

Done. The implementation is complete and verified.

**Files written (all under `workspace/implementation/`)**

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 9 | Foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op when Flask present) |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 43 | Flask app, ApiError/404/405/500 envelope handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 45 | In-memory dict store + logical clock (starts 2026-08-01T00:00:00Z, never wall-clock) |
| `errors.py` | 32 | ApiError + all 21 PRD error IDs |
| `response.py` | 44 | `meta`/`response_type`/`data` envelope; list pagination fields in meta |
| `auth.py` | 41 | `X-User-ID`/`X-User-Role` checks, 401/403, 5 roles |
| `utils.py` | 159 | ISO-8601 parse/format (3 fractional digits), field validators, limit/offset pagination |
| `services.py` | 636 | Serializers, hierarchical path resolution, exchange-vs-treatment determination, posture rollup, severity scoring, escalation, clock-driven transitions |
| `routes/__init__.py` | 9 | Blueprint registration |
| `routes/core.py` | 240 | Clock, vessels, plans |
| `routes/voyages.py` | 486 | Voyages, ballast events, determinations, reports |
| `routes/compliance.py` | 432 | Inspections, noncompliance, deficiencies, enforcement cases |
| `routes/ops.py` | 391 | Record books/entries, emissions, drills |

Total: 2,568 lines.

**Endpoints**: 52/52 from the PRD §4 table implemented (verified by route-count grep), including the `POST /_clock/set_current_utc` test-driving endpoint.

**Key behaviors implemented**

- Validation priority order (auth 401 → role 403 → path 404 → state 409 → OCC 412 → SoD/frozen → ordered 422 business checks), exact error IDs/HTTP codes from PRD §5
- OCC on the three guarded writes (`expected_vessel_version`, `expected_voyage_version`, `expected_deficiency_version` → 412)
- Determination algorithm with per-tank chronological uptake attribution, treatment-preferred dual compliance, EXEMPT_NO_US_EEZ/EXEMPT_SAME_COTP short-circuits, 3-decimal half-up volumes, `is_current` row rotation
- Full state machines: plans (with supersede cascade + PLAN_AMENDMENT recompute), voyage dual-axis (compliance × reporting), inspections (with 90-day reopen and NC un-close cascade), deficiencies (RECTIFIED→REOPENED with +7d deadline), record books (seal gates), emissions (scrubber/ECA/global thresholds, inclusive 0.10 boundary), drills (recurrence intervals, officer heuristic), enforcement (escalation-driven creation, linked-record close gate)
- Posture rollup (FROZEN on active hold_flag case; RESTRICTED on active case, open P1 deficiency, or recent unclosed CRITICAL), time-driven transitions (report overdue, drill overdue, NC escalation) re-evaluated on clock advance

**Boot verification**: Smoke-tested twice from fresh processes via `bash start.sh` on port 18923: boots in ~2s, `GET /vessels` returns an empty list on fresh boot (no seeding anywhere — storage is purely in-memory dicts), and 68 + 31 end-to-end checks covering every entity family, the determination variants, OCC, SoD, escalation, and clock transitions all passed (the single "FAIL" line was a bad expectation in the throwaway test script — the server's `is_overdue: true` was correct since the clock had already passed the deadline).

## Step 5: Generate Unit Tests — 2026-08-12T21:15:00.000Z

All checks pass. Generation complete. Summary:

**Files written**

`test_helpers/` (1,817 lines):
- `types.py` (462) — 20+ status/field enums, 14 entity TypedDicts; append-only `BallastWaterEvent`/`RecordBookEntry` omit `updated_at`/`version` per PRD §2.4
- `api_client.py` (271) — one method per PRD endpoint (51 methods)
- `api_errors.py` (54) — 20 error IDs + HTTP map registered with the framework
- `assertions.py` (208) — per-entity assertions + partition invariant + second-precision timestamp comparator (tolerant to `.000Z` rendering)
- `factories.py` (192), `constants.py` (56), `test_users.py` (41 — all roles opaque, plus per-user builders for SoD tests), `fixtures.py` (496 — clock, approved-plan, departed-voyage, OCC-aware event chain, PSC-exceedance, rectification, escalation fixtures)
- `__init__.py` (37) barrel export

`test_suite/` (3,413 lines):
- `conftest.py` (35) + 13 test files (`test_01_vessels` … `test_13_security`), **114 tests total**

**Test counts per queue**
- Queue A (Difficulty): 27/27 instances covered, ≥2 tests each — 54 tests
- Queue B (Corner): 59/63 non-stub instances covered, ≥1 test each — 60 tests; all 21 `excluded_because` stubs verified to resolve to real difficulty instances and not translated

**Instances skipped (PRD-first filter)**
1. `Corner/calculations/report_due_at_post_discharge_plus_6h` — PRD §3.4 defines the POST_DISCHARGE due rule but never states that/when the system instantiates a POST_DISCHARGE report; the asserted row is unreachable via PRD-declared pathways (coverage fails).
2. `Corner/endpoints/reports_filter_by_status` — PRD §2.3 declares only `limit`/`offset` query params; the `status` filter has no verbatim PRD coverage.
3. `Corner/endpoints/ballast_events_filter_by_tank_id` — same (tank_id/event_kind filters not in PRD).
4. `Corner/endpoints/noncompliance_filter_by_severity` — same (severity filter not in PRD).

**PRD-adjudication adjustments inside translated instances**
- `sulfur_eca_exactly_at_limit_compliant`: design pinned spawned-record severity MAJOR (from a state-machine side-effect note), but PRD §3.10's scoring uniquely derives 25 points → MINOR under OPEN posture; asserted MINOR per PRD.
- `critical_record_escalates_after_24h_boundary`: PRD's "has gone 24 hours without response" does not uniquely pin the exact +24h instant — asserted OPEN at +24h−1s and ESCALATED at +24h+1s; dropped the design's `linked_noncompliance_ids` length-2 literal (inconsistent with its own 3-escalation setup) in favor of the PRD-derivable "attaches to the existing ACTIVE case".
- `vessel_list_pagination_limit_and_offset`: both vessels share one logical-clock `created_at`, so intra-page order is not uniquely derivable — asserted page disjointness/union instead of "MV PageTwo on page 1".
- `standing_record_book_defaults_open_without_voyage`: dropped `voyage_id is null` (default-value silence pattern); kept OPEN-status assertion.
- `rectification_deadline_a15_identified_plus_14d`: PRD doesn't pin `identified_at` for system-created deficiencies — asserted deadline == identified_at + 14 days relative to the row's own anchor instead of the absolute literal.

**Self-check results**
- Stage 1: all modules compile, `test_helpers` imports cleanly against the installed `prd_bench_local_runner.testing`, error map registered (20 entries), pyflakes clean (only unused-import noise filtered, zero undefined names).
- Stage 2: pytest collects 114/114 tests with no import errors; audit script confirms every test carries exactly one `Design:` line resolving to a real instance (no untagged, no dual-tagged, no stub-referencing, no unresolved tags); queue A 27/27 ≥2, queue B 59/63 ≥1 with the 4 skips above; 199 rule-bearing docstring quotes all survive literal grep of PRD.md (C1/C2/C3); zero `skip`/`skipif`/`xfail` markers; zero scaffold references in generated code comments/docstrings.

## Step 7: Run Tests and Iterate — 2026-08-12T21:46:18.000Z

Clean 8-round parallel sweep: all 8 rounds passed 114/114 (orchestrator-verified: results.1–8.json each report total=114 passed=114 failed=0 errors=0 skipped=0). The loop exit criterion is met.

**Iterations run:** 3 sweeps (24 total round executions).

**Tests deleted:** None. Every failing assertion traced to verbatim PRD prose; the two deterministic failures were implementation bugs, and the flaky failures were harness/infrastructure issues — no test met a deletion criterion.

**Fixes applied to `implementation/`:**

1. `routes/voyages.py` — `create_ballast_event()`: event `volume_m3` is now carried at 3 decimal places, rounded half up, at intake (`round3(...)`), so the per-tank balance check and the determination sums all operate on carried volumes. PRD §2.6 ("Volumes and percentages are carried to 3 decimal places and rounded half up") is system-wide, so the only consistent reading is round-then-carry: two 100.0005 discharges yield `treatment_compliant_volume_m3 == 200.002`. Previously the implementation summed raw floats and rounded only the total (200.001). Fixed `test_determination_rounds_each_event_volume_before_summing` (8/8 rounds) and `test_rounded_event_volumes_carry_into_basis_classification`.

2. `routes/ops.py` — `create_entry()`: removed the append-time 400 rejection for missing `countersigned_by` on OILY_WATER/SEWAGE books. PRD §3.7 lists `countersigned_by` among the *optional* append fields ("carries ... and optionally `countersigned_by`...") and names the seal transition as the enforcement point ("Sealing requires ... every entry in the book must carry its required countersignature"). The seal gate already existed in `seal_book()`. The append-time check was scaffold-only strictness that contradicted the PRD payload shape and made the PRD's seal clause unreachable. Fixed `test_seal_with_missing_countersignature_returns_409` (8/8 rounds).

3. `app.py` — `__main__`: bind-retry loop (up to 20s) around `app.run()` so a not-yet-released port from the just-killed per-test predecessor cannot fail a boot. Startup robustness only; no API behavior change.

**Fixes applied to `test_helpers/`:**

4. `test_helpers/api_client.py` — `ApiClient`: set `Connection: close` on the session and added a single transparent retry on `requests.exceptions.ConnectionError`. The session-scoped client's keep-alive pool could hold a stale connection to the server SIGKILLed by per-test-server isolation, surfacing as mid-test `RemoteDisconnected`/`ConnectionResetError` (sweep 2: `test_inspection_evaluate_clean_has_no_side_effects`, `test_reopen_at_exactly_ninety_days_succeeds`, one round each). The server is only ever killed between tests, so a connection error means the request never reached a live handler — retry is safe for mutating and idempotent requests alike. Transport reliability only; no assertion changed.

**Flaky infra (no code fix possible/needed):** four tests across sweeps 1–2 errored with runner-level "API server could not be restarted" (15s boot-poll window) — correlated with external load (the shared host's port registry showed 19–26 concurrent holders from other pipelines' sweeps). The bind-retry plus connection hardening eliminated all recurrence in sweep 3.

**Final state:** sweep 3 — all 8 rounds 114/114 passed, failure union empty.

## Step 8: Finalize PRD — 2026-08-12T21:55:00.000Z

PRD_FINALIZED.md is written. Summary:

**Line counts and delta**
- PRD.md: 276 lines; PRD_FINALIZED.md: 276 lines (0% line-count delta — both edits are inline within existing single-line paragraphs; character-level delta is two sentences added/extended on lines 118 and 162).

**Changes**
- §3.2 (Voyage Lifecycle and Ballast Water Events) — insert — after "`volume_m3` (greater than 0)" added: the event's `volume_m3` is rounded half up to 3 decimal places when recorded, the carried value is persisted, and the per-tank balance check, the single-event capacity check, and the determination's volume sums all operate on carried per-event values (round-then-sum, so two 100.0005 discharges yield 200.002) — `implementation/routes/voyages.py:222`, `implementation/services.py:406,465-468`.
- §3.7 (Record Books and Statutory Entries) — revise — "A countersignature is required for `OILY_WATER` and `SEWAGE` entries" now pins enforcement timing: enforced at sealing, not at append; an entry may be recorded without it and the seal operation is what is rejected while any entry in an `OILY_WATER`/`SEWAGE` book lacks one — `implementation/routes/ops.py:139` (append reads `countersigned_by` as optional, no check) and `implementation/routes/ops.py:199-206` (seal gate raises `ERR_INVALID_STATE` 409).
- Items 3 (`app.py` port bind-retry) and 4 (`test_helpers/api_client.py` connection retry): no PRD edit — pure startup/transport robustness with no API-behavior surface.

**Per-edit pre-edit search log**

Edit 1 (volume rounding site)
- (a) Subject: where half-up 3-decimal rounding applies in the event-intake → balance → capacity → determination pipeline.
- (b) Paths enumerated and read: `routes/voyages.py:222` (round3 at intake, before all validations), `voyages.py:280-304` (chronological per-tank balance uses `Decimal(str(e["volume_m3"]))` of stored events and `Decimal(str(volume))` for the candidate), `voyages.py:307-310` (capacity check compares the rounded `volume` against `ballast_capacity_m3`), `voyages.py:317` (persists carried value), `services.py:191` (`event_json` serializes the stored value), `services.py:406,426,445,447,449` (determination sums stored volumes), `services.py:465-468` (round3 re-applied to sums — idempotent on already-carried inputs), `services.py:40-42` (`round3` = Decimal quantize 0.001 ROUND_HALF_UP). Also confirmed `distance_from_shore_nm` and `salinity_ppt` are NOT rounded at intake (`voyages.py:233-237`), so the wording is scoped to `volume_m3` only.
- (c) Adjustment: explicitly named all three downstream consumers (balance, capacity, determination sums) rather than only the Step 7 sites (balance/determination), since the capacity check also uses the carried value; kept §2.6 and §3.3 prose verbatim as they remain consistent.

Edit 2 (countersignature enforcement timing)
- (a) Subject: when the OILY_WATER/SEWAGE countersignature requirement is enforced (append vs seal).
- (b) Paths enumerated and read: `routes/ops.py:119-167` (`create_entry` — `countersigned_by` via `opt_str`, no validation for any book kind), `routes/ops.py:187-211` (`seal_book` — check scoped to `book_kind in ("OILY_WATER", "SEWAGE")`, applied to every entry in the book, raises `ERR_INVALID_STATE` 409), `services.py:318` (`entry_json` serializes the field). Cross-checked the PRD seal sentence ("every entry in the book must carry its required countersignature") and the fixed test `test_seal_with_missing_countersignature_returns_409` for confirmation.
- (c) Adjustment: phrased as "any entry in an `OILY_WATER` or `SEWAGE` book" (matching the impl's book-kind-scoped check over all entries) instead of entry-kind-scoped wording, and did not name an error code since the PRD's seal clause deliberately leaves the rejection to the generic state-transition rule.

## Step 9: Complete PRD — 2026-08-12T22:15:00.000Z

Done. `workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`, pinning every behavior found in `implementation/`.

**Source vs result**: PRD_FINALIZED.md 276 lines / 42,159 chars → PRD_COMPLETED.md 279 lines / 48,415 chars (char-delta +6,256). No sections added or removed; all changes are in-paragraph inserts/revisions plus one error-table row.

**Counts**: 33 ambiguity-pins, 7 mismatch-revisions (40 total).

**Changes** (impl paths relative to `workspace/implementation/`):

- §2.3 — insert — ambiguity — limit>100 clamped not rejected, non-integer/low limit or negative offset → ERR_VALIDATION 400, created_at tie-break by creation order, `has_more` formula — utils.py:123-138,157-159; response.py:33
- §2.6 — insert — ambiguity — 3-decimal half-up rounding applies only to event `volume_m3` and determination volumes; entry `quantity`/`sulfur_content_pct` persisted as supplied — services.py:40-42; routes/voyages.py:222; routes/ops.py:130
- §2.7 — insert — ambiguity — expected-version field must be present integer (else ERR_VALIDATION); stale check runs after path+state checks, before frozen/payload checks — routes/core.py:121-125; routes/voyages.py:209-214; routes/compliance.py:294-298
- §2.8 — revise — ambiguity — RESTRICTED also applies while any enforcement case is active on the vessel — services.py:503
- §2.8 — revise — mismatch — FROZEN gate is exactly five operations (depart, arrive, ballast-event, manual recompute, report submit); all other operations ungated — routes/voyages.py:116,160,214,400,443
- §3.1 — insert — ambiguity — duplicate/malformed `imo_number` → ERR_VALIDATION 400; `gross_tonnage` integer ≥ 1 — routes/core.py:53-57,67
- §3.1 — insert — ambiguity — `bwms_installation_date` accepted and stored when bwms_type NONE — routes/core.py:64-66
- §3.1 — insert — ambiguity — plan submit precondition violation → ERR_INVALID_STATE 409 — routes/core.py:183-186
- §3.1 — insert — ambiguity — PLAN_AMENDMENT recompute increments each non-terminal voyage's version; withdraw leaves vessel version unchanged — routes/core.py:221-225,237-240
- §3.2 — insert — ambiguity — ports accepted as opaque non-empty strings (no UN/LOCODE validation) — routes/voyages.py:51-52
- §3.2 — insert — ambiguity — departure without APPROVED plan → ERR_INVALID_STATE 409 — routes/voyages.py:117-123
- §3.2 — insert — ambiguity — PRE_ARRIVAL `due_at` null until arrival, filled (only if still null) at arrival — routes/voyages.py:136-137,167-173
- §3.2 — insert — ambiguity — event recording not gated on `compliance_status`; lat/lon must be numbers; distance ≥ 0; salinity ≥ 0; source_port non-empty; volume >0 checked pre-rounding — routes/voyages.py:216-236
- §3.2 — insert — ambiguity — window bounds inclusive (no upper bound pre-arrival); prior UPTAKE at-or-before counts; balance replay applies new event after same-timestamp existing events — routes/voyages.py:239-305
- §3.3 — revise — ambiguity — discharge attribution uses UPTAKE at-or-before; treatment/exchange windows inclusive both ends — services.py:421,430,437
- §3.3 — revise — mismatch — open-ocean test applied to event's `distance_from_shore_nm` ≥ 200 (coordinates not consulted); no exchange path while no plan APPROVED — services.py:434-442
- §3.3 — revise — mismatch — EXEMPT_SAME_COTP triggered by `crosses_captain_of_port_zones` false alone; exemptions checked in fixed order; exempt basis zeroes the three classified volumes while `total_discharged_volume_m3` still sums — services.py:411-416
- §3.3 — revise — mismatch — arrival commit branch order: compliant basis wins regardless of open records; OPEN MAJOR/CRITICAL forces NONCOMPLIANT only for non-compliant bases; EXEMPT does not increment vessel version; INSUFFICIENT_DATA leaves voyage IN_PROGRESS — routes/voyages.py:175-195
- §3.4 — insert — ambiguity — POST_DISCHARGE instantiated on first DISCHARGE; `due_at` moves to latest discharge +6h while DRAFT — routes/voyages.py:328-348
- §3.4 — revise — mismatch — ANNUAL_SUMMARY is never instantiated by the system — (no occurrence anywhere in implementation/)
- §3.4 — insert — ambiguity — OVERDUE flip only from DUE; REPORT_OVERDUE record created once per report regardless — services.py:601-608
- §3.4 — insert — ambiguity — `payload_summary` required non-null; `rejection_reason` required non-empty string — routes/voyages.py:445,483
- §3.5 — insert — ambiguity — `exceeded` null until evaluation; `last_psc_inspection_at` set to `sampled_at` without vessel version increment — routes/compliance.py:57,61-62
- §3.5 — insert — ambiguity — auto-created deficiency: code 14806, `identified_at` = inspection `sampled_at`, deadline +14d, priority-one — routes/compliance.py:117-132
- §3.5 — revise — ambiguity — reopen window inclusive through `sampled_at` + 90 days — routes/compliance.py:172
- §3.7 — insert — ambiguity — creating BALLAST_WATER book via endpoint → ERR_VALIDATION 400; supplied `voyage_id` must resolve to a voyage of the vessel — routes/ops.py:73-83
- §3.7 — insert — ambiguity — discharge-type kinds enumerated (DISCHARGE, DISCHARGE_SEA, DISCHARGE_RECEPTION, DISCHARGE_TREATED, DISCHARGE_UNTREATED, BILGE_DISCHARGE); missing position/distance → ERR_VALIDATION 400 — routes/ops.py:36-40,140-147
- §3.7 — insert — ambiguity — seal countersignature failure → ERR_INVALID_STATE 409 — routes/ops.py:201-205
- §3.8 — revise — mismatch — scrubber rule: EXEMPT_SCRUBBER iff any `inside_eca_hours` logged, COMPLIANT if none; no 95% EGCS ratio is verified — routes/ops.py:277-281
- §3.8 — revise — mismatch — BIOFUEL_BLEND compared directly like other fuels; no pro rata ECA/non-ECA split — routes/ops.py:283-286
- §3.8 — revise — ambiguity — only a COMPLIANT outcome increments vessel version; EXEMPT_SCRUBBER does not — routes/ops.py:289-290
- §3.9 — insert — ambiguity — completion `completed_at`/`attendees` optional (default now / scheduled list); `next_due_at` = `completed_at` + interval; officer detection heuristic (string contains "officer", rank/role/title/position keys, or officer/is_officer flags) — routes/ops.py:47-60,352-371
- §3.9 — insert — ambiguity — drill-spawned MISSING_METHOD record carries no `voyage_id` — services.py:624
- §3.10 — insert — ambiguity — response after deadline → ERR_INVALID_STATE 409 — routes/compliance.py:221-223
- §3.10 — revise — ambiguity — CRITICAL escalation threshold is 24h since `detected_at` — services.py:631-634
- §3.10 — insert — ambiguity — escalation flips record `response_status` to ESCALATED; escalation-created case opens NOTICE_OF_VIOLATION with `hold_flag` false — services.py:559-576
- §3.11 — insert — ambiguity — `penalty_assessed` optional, defaults false, non-boolean → ERR_VALIDATION; CLOSED_PENALTY has no linked-record-closed requirement — routes/compliance.py:390-408
- §3.12 — insert — ambiguity — clock set verbatim to supplied value; endpoint returns 200 with empty data object — routes/core.py:33-41
- §4 — insert — ambiguity — enumerated exact-match query filters per list endpoint — routes/core.py:93-94,158; routes/voyages.py:88-89,359-360,383,417-418; routes/ops.py:100-102,174,256,330-331; routes/compliance.py:72-73,198-199,256-257,355
- §5 — insert — ambiguity — added ERR_INTERNAL (500) row; undefined paths/methods → ERR_NOT_FOUND 404 — errors.py:32; app.py:21-34

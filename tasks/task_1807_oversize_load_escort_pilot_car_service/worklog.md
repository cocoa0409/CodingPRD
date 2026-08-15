# Worklog — task_1807_oversize_load_escort_pilot_car_service

## Step 1: Create Task Directory — 2026-08-14T17:50:00.000Z

Task directory `tasks/task_1807_oversize_load_escort_pilot_car_service/` and `workspace/` already created by pipeline launcher (per command args); orchestrator skipped index scan/creation as instructed. User difficulty directive: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-14T18:34:00.000Z

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD.yaml` — 1849 lines (§1.0–§1.7 + complexity_profile; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 776 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD_CORNER_DESIGN.yaml` — 1700 lines (single top-level key `scaffold_corner_design`)

## Element counts
- Entities: **11** (Carrier, Escort, Job, RouteLeg, Permit, RouteSurvey, Obstruction [common_fields: false, append-only], EscortAssignment, DelayEvent, Incident, Invoice)
- State machines: **9** (Job cyclic EN_ROUTE↔ON_HOLD + QUOTED→DRAFT amendment revert; RouteLeg BLOCKED↔DETERMINED re-survey loop; RouteSurvey with ACCEPTED→SUPERSEDED; EscortAssignment branching; Permit with clock-swept EXPIRED; DelayEvent; Incident ASSESSED↔DISPUTED cycle; Invoice FINALIZED↔DISPUTED revision loop; Escort ACTIVE↔SUSPENDED)
- Calculations: **13** (incl. dual-variant quote/final pricing, dual-variant map/surveyed clearance, per-event-rounded standby billing, pinned-order invoice composition, selector policy, two interval-overlap rules with different semantics)
- Validations: **18** priority rows
- Endpoints: **58** (incl. `POST /_clock/set_current_utc` with startup default 2026-08-01T00:00:00Z)
- Errors: **43**
- Roles: **7** (2 entity-backed: CarrierRep→Carrier, EscortOperator→Escort; 5 opaque; segregation_of_duties enforced person-level on incident assess and invoice finalize/adjust)
- Concurrency rules: **2** (OCC on Job.version for amendments; OCC on RouteLeg.version for survey accept/supersede)

## §1.8 / §1.9
- §1.8: **19 instances** across all 9 rules (each rule ≥2; combinatorial_formula covers modes (a), (b), and (c); cascades from two different triggers at depth 3; two conserved quantities; two interval semantics on different resources; all formula-derived asserts pre-computed to literals, e.g. quote 47500 vs final invoice 71960, tier-2 composition total 217087, top-tier 548760, liability cap share 24950000)
- §1.9: **75 entries** — 60 active corner instances + 15 `excluded_because` stubs, spanning all nine taxonomy sections

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD.yaml
  Difficulty design:  tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_1807_oversize_load_escort_pilot_car_service/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     11
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1148

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage-audit notes
- **Error catalog**: all 43 errors are referenced by a validation/transition and each has a live trigger in §1.8 or §1.9 (the one initial gap, `ERR_HEIGHT_POLE_EQUIPMENT_MISSING`, was fixed by adding `height_pole_equipment_missing_rejected`; the only "referenced-but-not-catalogued" token is `ERR_XXX` inside the fixed §1.0 envelope template, which is verbatim boilerplate, not a reference).
- **Grounds audit** (scripted, beyond lint): every `grounds:` entry in both design files resolves to a declared calculation/entity-field/transition/error/validation-priority/concurrency-rule/endpoint/role; all 94 instance names unique across both files; all 15 stub citations resolve to existing §1.8 instance names; no stub carries a test_recipe.
- **FK reverse-reachability**: all 11 FKs have sub-resource or filtered-list GETs (lint check (f) clean).
- **Enum closure**: every system enum value has a producing transition/system event (spot-check script found no unproduced values).
- **Forbidden vocabulary scan**: no "simultaneously"/"first-writer-wins"/"race winner"/"in parallel" etc. anywhere in the three files.
- **Replay notes**: all setup chains replayed call-by-call against §1.2/§1.4 (clock positioned before every `started_at`; deliver comms gaps pinned at 60/29/90 minutes; OCC version inputs always captured `${var}` or `${var} - 1`, never literals; negative triggers capture `$.data.error_id`).
- Two YAML authoring fixes applied along the way: bracketed JSONPath captures (`$.data[0].id`) and bracketed grounds entries (`errors[...]`, `validations[priority=N]`) required quoting in flow context.

## Step 3: Copy Shared Files — 2026-08-14T18:35:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1807_oversize_load_escort_pilot_car_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T18:47:00.000Z

All audits pass. The PRD is complete and verified.

## Generation Report

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/workspace/PRD.md` — 371 lines

**Section inventory:**
- §1 Introduction (2 paragraphs — business-context angle)
- §2 Global Specifications (11 subsections): 2.1 RBAC with per-role identity prose (CarrierRep/EscortOperator entity-backed; Dispatcher/RouteSurveyor/SafetyManager/BillingClerk/FinanceManager opaque, each individually named); 2.2 API Response Structure (**verified byte-identical** to `section-2.2-response-structure.md`); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending with the `sequence_index` leg exception); 2.4 Logical Time and the System Clock (startup default 2026-08-01T00:00:00Z, sweep cascade); 2.5 Common Resource Properties (Obstruction called out as `id`+`created_at` only); 2.6 Units/Monetary Precision; 2.7 Hierarchical Consistency and Cascade Semantics; 2.8 Nested Resource Retrieval (left-to-right, all ten 404 ids); 2.9 OCC; 2.10 Carrier Credit Availability; 2.11 Validation Order (full 18-priority pipeline in explicit order)
- §3 Business Logic (8 subsections): registration → booking/amendment → requirement determination/quote/acceptance → permits/police/surveys → assignments/selection/scheduling gates → movement/holds/delivery/cancellation → standby/incidents/reliability → invoicing/disputes/settlement. No paths or HTTP methods anywhere in §3; all four state-rule tables (TX/OK/KS/LA) rendered at equal density; all 13 calculations in precise natural language (thresholds inclusive, ceil-to-half-hour, 30/15-minute standby rounding pinned per event, pinned 9-step invoice evaluation order, 60-minute deadhead buffer with the 120/119-minute boundary, half-open curfews with all 8 windows)
- §4 Endpoint Definitions: exactly **58 rows**, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue: exactly **43 rows**, 2 columns (Error ID, HTTP Status Code)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].request_body/query_params/path_params: 122 required, 122 present, 0 missing
  (pass 1 found 8 missing status-field names — job_status, job_id, leg_status, permit_status, survey_status,
   delay_status, incident_status, invoice_status — repaired in pass 2 by naming each status field at its
   lifecycle introduction; re-run confirms empty diff)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed in prose (§2.11 ordered pipeline + per-endpoint sequences in §3), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (amendments/expected_job_version/ERR_STALE_JOB_VERSION/412; survey accept/expected_leg_version/ERR_STALE_LEG_VERSION/412; "no other endpoint takes a version field" stated), 0 missing
- state_machines[].transitions: 33 checked across 9 machines, 33 fully expressed (preconditions paired with error ids, side effects incl. demotion/release/supersede/credit cascades), 0 missing
- calculations[]: 13 checked, 13 fully expressed with constants embedded (no pseudocode operators, no fuzzy words — verified by scan), 0 missing
- validations[] conditions: 18 checked, all 43 error ids matchable to conditions in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: defaults and null-until semantics stated for every entity (reliability 100, pole defaults, quote-field nulls, cancel_fee 0/null tier, issued_at/decided_at/rejection_reason nulls, assignment timestamp nulls, delay-event nulls, assessment nulls, invoice nulls), 0 missing
- sibling-branch symmetry: 6 groups checked (4 state-rule paragraphs, accept/reject survey, payment/write-off, billable/non-billable causes, decline/release conservation, DRAFT→DRAFT vs QUOTED→DRAFT amendments), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 655
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No pseudocode operators (`>=`, `==`, `ceil(`, `->`, etc.) or fuzzy hedging words appear anywhere outside the verbatim §2.2 block (mechanically verified).

## Step 5: Generate Unit Tests — 2026-08-14T19:12:00.000Z

Generation complete. Verbatim summary per the skill's reporting requirements:

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/test_helpers/` — 9 files**
`__init__.py` (barrel), `types.py` (20 enums + 11 entity TypedDicts; Obstruction correctly omits `updated_at`/`version` as append-only), `api_client.py` (50 methods, one per PRD endpoint; note there is no `GET /escorts/{id}` — single-escort reads go through a roster-scan helper), `api_errors.py` (41 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + invoice composition invariant), `factories.py`, `constants.py` (state rule tables, curfew windows, all monetary constants), `test_users.py` (shared opaque-role headers + mandatory per-instance builders for entity-backed CarrierRep/EscortOperator), `fixtures.py` (atomic helpers + tiered composites: `setup_booked_job` / `advance_to_cleared` / `advance_to_scheduled` / `advance_to_en_route` / `advance_to_delivered` / `setup_delivered_rear_job` / `setup_delivered_superload_tx` / `setup_en_route_one_position_job`, with a `clock_base` parameter so multi-job scenarios never move the logical clock backward).

**`/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/test_suite/` — 14 files**
`conftest.py` + `test_01_envelope_pagination_filters.py` (4) + `test_02_registry_and_not_found.py` (3) + `test_03_job_booking_and_amendment.py` (5) + `test_04_quote_requirements.py` (7) + `test_05_permits_surveys_clearance.py` (11) + `test_06_assignments_selection.py` (12) + `test_07_scheduling_gates.py` (8) + `test_08_movement.py` (7) + `test_09_delay_standby.py` (7) + `test_10_cancellation_credit.py` (9) + `test_11_incidents.py` (10) + `test_12_invoices.py` (10) + `test_13_rbac.py` (3) = **96 tests**.

## Tests emitted per queue

- **Queue A (Difficulty): 38 tests across all 19 instances** — every instance has exactly ≥2 tagged tests (19/19).
- **Queue B (Corner): 58 tests across 58 of 60 non-stub instances** — every emitted instance has ≥1 tagged test. All 15 `excluded_because:` stubs were left untranslated; all 15 stub `difficulty_instance` pointers resolve to real §1.8 instance names (verified programmatically).

## Instances skipped (PRD-first two-condition filter)

1. **`Corner/entities/computed_and_system_fields_input_ignored`** — *non-unique-derivability*. PRD never states how the server treats client-supplied computed/system fields in a create body; both "ignore extras and return 201 with defaults" and "reject unknown fields with 400" are PRD-consistent readings (§2.11 item 3 enumerates required-presence/type/enum/range failures only).
2. **`Corner/state_machines/assignment_creation_state_gates`** — *no verbatim PRD coverage for the asserted outcome*. The instance's headline claim (offer on a DRAFT job → `ERR_JOB_INVALID_STATE`, i.e. job-gate-before-leg-gate) contradicts the only PRD sentence governing offers: "Offering a position targets a leg in `DETERMINED` or `CLEARED` status — any other leg status is rejected with `ERR_LEG_INVALID_STATE`", which uniquely derives the leg error for a DRAFT job's PENDING leg. The instance fails as designed; the gap stays a gap.

## Stage 2 self-audit results

- **Scaffold-citation pass (C4):** every one of the 96 tests carries exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line, copied verbatim from the source YAML `name:`; zero unknown tags, zero untagged, zero dual-tagged (programmatic audit).
- **PRD-citation pass (C1/C2/C3):** every docstring's quoted rule text contains a ≥8-word fragment surviving a literal whitespace-normalized grep of `PRD.md` — clean across all 96 tests.
- **No `pytest.mark.skip` / `skipif` / `xfail`** anywhere in the generated tree; no "scaffold" references in generated code comments/docstrings.
- **`pytest --collect-only`:** 96 tests collected, all imports resolve against the framework.
- **Two-reader adjustments made during translation** (not skips): the enum-out-of-membership test uses `validate_error_is_one_of([ERR_INVALID_ENUM_VALUE, ERR_INVALID_REQUEST])` per PRD §2.11's explicit "may instead return" license; `incident_and_delay_require_active_job` sets the delay's `started_at` ≤ the logical clock so only the job-state rule can fail (the recipe's original timestamp would have surfaced the shape check at pipeline item 3); the `filter_and_list_composition` test asserts only the PRD-named filters (escort `state_code` array-membership, assignment `escort_id`/`assignment_status`) because the PRD never names the `/jobs` filter parameters.

## Step 6: Generate Implementation — 2026-08-14T19:12:00.000Z

Complete. Final report:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` | 1 |
| `app.py` (entry, blueprint registration, envelope error handlers, 0.0.0.0:$PORT) | 47 |
| `db.py` (empty in-memory stores + logical clock defaulting to 2026-08-01T00:00:00Z) | 43 |
| `errors.py` (full error catalog) | 73 |
| `response.py` (envelope: `meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more`) | 83 |
| `middleware.py` (X-User-ID/X-User-Role auth, 7 roles, ownership) | 50 |
| `mutate.py` (one version bump + `updated_at` refresh per mutated resource per operation) | 26 |
| `util.py` (ISO-8601 parse/format with 3 fractional digits, body/field validators) | 137 |
| `serializers.py` (wire shapes; computed-on-read credit/ytd/active-count) | 278 |
| `services/calc.py` (all 13 calculation rules, Decimal ROUND_HALF_UP) | 305 |
| `services/cascade.py` (gates, promotions/demotions, releases, clock sweep, selector) | 203 |
| `routes/clock.py`, `carriers.py`, `escorts.py`, `jobs.py`, `legs.py`, `permits.py`, `surveys.py`, `assignments.py`, `delays.py`, `incidents.py`, `invoices.py` | 21+48+102+420+143+40+154+220+92+174+215 |
| `routes/__init__.py`, `services/__init__.py` | 0 |

Total 2,885 lines.

## Coverage
- **Endpoints: 58/58** from scaffold §1.5 (clock 1, carriers 3, escorts 4, jobs 12, legs 7, permits 1, surveys 4, assignments 8, delay events 3, incidents 7, invoices 8).
- **State machines: 9/9** (Job incl. hold/resume and cancel-tier cascade, RouteLeg incl. BLOCKED/reopen, Permit incl. clock-sweep expiry, RouteSurvey incl. supersede chain, EscortAssignment, DelayEvent, Incident incl. dispute loop, Invoice incl. dispute/adjust loop, Escort suspend/reinstate).
- **Calculations: 13/13** (per-state requirement determination with inclusive thresholds; dual-variant clearance with equality-passes; quote estimate with ceil-to-half-hours; final billing 30-min ceil before 4h floor; per-event standby rounding; pinned 9-step invoice composition with tier basis = ytd+subtotal and pre-discount fuel surcharge; selector reliability-DESC/created_at-ASC; buffered overlap with touching-allowed; half-open recurring curfews; liability cap/deductible; credit availability; cancellation tiers keyed on pre-cancel state; reliability penalties with auto-suspension floor).
- **Errors: 43/43** catalog IDs with exact HTTP statuses; validation pipeline follows §1.4 priority order (auth → role → body → path → body-FK → ownership → state/OCC → safety → permit guard → temporal → referential → SoD → credit → payment). OCC: `expected_job_version` (412) and `expected_leg_version` (412) only on the two declared endpoints.
- **Storage:** in-memory dicts only, empty at boot; no seeding anywhere.

## Self-audit results
- Three runtime smoke suites (written to /tmp, not the task dir): **224 assertions, all passing** — covering full happy path (book→quote→accept→permit→survey FAIL/PASS→assign→schedule→depart→delay→deliver→incident→settle→invoice→dispute→adjust→pay→close), every 404/409/422/412/402 error path, envelope shape, pagination meta, cancel tiers (NONE/10/25/50), credit conservation across book+cancel, clock-sweep demotion, suspension cascades, curfew/holiday/permit-window boundaries, 120-vs-119-minute overlap boundary, 90-minute check-in boundary, 30/31/45/46-minute standby rounding, and 5% volume tier.
- `bash start.sh` cold-boot verified twice consecutively: fresh empty store, default logical clock, HTTP 200 within ~2.5s; per-test-server restart contract satisfied (guarded dependency install is a no-op once Flask is present).
- Notable fidelity decisions: leg version is NOT bumped on survey submit (scaffold annotates the leg bump only at accept/reject); escort `active_assignment_count` and carrier credit/YTD are computed on read (never stored, never bump versions); `ERR_INVALID_ENUM_VALUE` is returned only for the catalog-listed enums (position, cause, outcome, incident_type, obstruction_type, disposition) while invalid `state_code`/`certified_state_codes` return `ERR_INVALID_REQUEST` per PRD §3.2 and the catalog membership list.

## Step 7: Run Tests and Iterate — 2026-08-14T19:25:00.000Z

## Summary

**Iterations run:** 2 (sweep 1: baseline diagnosis; sweep 2: clean 8/8 verification — all rounds 96/96 passed).

**Tests deleted (with PRD-silence category):** None deleted outright. One test was trimmed per STEP 1c (partial coverage):
- `test_01_envelope_pagination_filters.py::test_pagination_defaults_and_bounds` — removed the two assertions that `limit=0` and `limit=101` are rejected with `ERR_INVALID_REQUEST`. **Silence category: validation-consequence silence (scaffold-only rule).** The scaffold corner design (`SCAFFOLD_CORNER_DESIGN.yaml` → `pagination_defaults_and_bounds`) states "limit 0 and 101 are out-of-range 400s", but the doc-generator never rendered a refusal rule into PRD prose: §2.3 says only "defaults to 10, with a minimum of 1 and a maximum of 100" (no consequence for out-of-range values), and §2.11's validation pipeline is explicitly scoped to "mutating request"s, so its numeric-range → `ERR_INVALID_REQUEST` mapping does not reach GET query params. Two faithful PRD-only readers diverge (reject vs clamp). Cross-benchmark evidence: sibling task_0946's PRD contains an explicit refusal sentence ("A `limit` outside the inclusive range 1 through 100 … is refused with `ERR_INVALID_PAGINATION`") and there the bounds test is fair; task_1807's PRD lacks any such sentence. The covered assertions (default limit 10, offset paging, `total_count`/`has_more`, in-range `limit=5` capping page size) were kept and strengthened.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/test_suite/test_05_permits_surveys_clearance.py` — added missing `submit_survey_payload` to the `from test_helpers import (...)` list; the test used it at line 233 (double-submit rejection, PRD §3.4 verbatim) but never imported it, producing `NameError` in all 8 rounds. Pure test bug; implementation was correct.
- `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/test_suite/test_01_envelope_pagination_filters.py` — STEP 1c trim described above (removed the two PRD-uncovered bounds-rejection assertions; added a covered in-range `limit=5` page-size check with an explanatory comment).

**Fixes applied to `implementation/`:** None — the implementation (including its PRD-consistent clamping of out-of-range pagination params) required no changes.

**Feedback notes for generators:** (1) doc-generator: Zero-Silence Rule violation — scaffold corner `pagination_defaults_and_bounds`'s "out-of-range 400s" consequence never reached PRD §2.3/§2.11 prose; (2) unit-test-generator: `submit_survey_payload` used without import in test_05 — a collect-time lint (e.g. compiling each module) would have caught the NameError before the sweep.

## Step 8: Finalize PRD — 2026-08-14T19:32:00.000Z

Done. PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/workspace/PRD_FINALIZED.md` with exactly one scoped edit.

## Summary

**Line counts / delta:** PRD.md = 371 lines; PRD_FINALIZED.md = 371 lines; 0% line-count delta (one in-place sentence revision on line 74, no sections added or removed).

**Changes:**
- §2.3 — revise — appended the consequence for out-of-range pagination query params: integer `limit`/`offset` values outside the supported ranges are clamped to the nearest bound (limit<1→1, limit>100→100, offset<0→0) rather than rejected, and the effective values are echoed in the response's pagination fields — `implementation/response.py:69-74` (parser), echoed via `response.py:29-34`.

**Step-7 traceability:** The pagination-bounds trim in `test_01_envelope_pagination_filters.py` was the only PRD silence in the diff (validation-consequence silence: §2.3 pinned min/max but no consequence, and §2.11's pipeline is scoped to mutating requests). The `submit_survey_payload` import fix was a pure test bug — no PRD edit traces to it, per instructions. No other edits were made.

**Per-edit pre-edit search log:**

Edit 1 (§2.3 pagination clamping):
- (a) Subject: pagination `limit`/`offset` query-parameter handling on list endpoints — defaults, bounds, and the consequence of out-of-range values.
- (b) Impl paths enumerated and read/grepped: `response.py:56-75` (`pagination_params` — the sole parser; defaults 10/0; non-integer raises `ERR_INVALID_REQUEST` at lines 62-66; integer out-of-range clamped at lines 69-74); `response.py:78-83` (`paginate` — slices `rows[offset:offset+limit]` with effective values); `response.py:29-42` (`success_list` — echoes post-clamp limit/offset in `meta`, computes `has_more` from them); all 13 list-endpoint call sites — carriers.py:39, delays.py:69, escorts.py:79, incidents.py:95 & 115, invoices.py:110, legs.py:44/104/143, surveys.py:154, jobs.py:167, assignments.py:134/157 — every one routes through `paginate`, so behavior is uniform. A grep of all `request.args` reads confirmed the only other query params are unrelated filters (state_code, escort_status, assignment_id, incident_status, escort_id, leg_id, assignment_status, carrier_id, job_status). PRD-side grep confirmed no competing range-consequence statement (line 244's "clamped between 0 and 100" concerns `reliability_score`, a different subject), and §2.11's numeric-range → `ERR_INVALID_REQUEST` mapping is explicitly scoped to "mutating request" bodies (line 133), so a GET query-param clamping sentence in §2.3 does not collide with it.
- (c) Wording adjustment: qualified the claim as "**Integer** values outside these ranges" so the sentence neither asserts nor denies the impl's non-integer rejection (`response.py:62-66`) — that path was outside the Step 7 trim's scope, so the PRD stays silent on it; and added "the effective values are the ones carried in the response's pagination fields" to remain consistent with `success_list` echoing post-clamp values at all 13 call sites.

## Step 9: Complete PRD — 2026-08-14T19:45:00.000Z

All edits are in place and verified. The diff is confined to in-paragraph inserts/revisions — no new sections, no restructured prose.

## Summary

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (both in `/home/ubuntu/github/CodingPRD/tasks/task_1807_oversize_load_escort_pilot_car_service/workspace/`)
- Lines: 371 → 375 (+4); chars: 68,043 → 72,425 (**+4,382**); 22 diff hunks, all inside existing paragraphs.
- **Ambiguity-pins: 18** · **Mismatch-revisions: 2**

### Changes

- **§2.2** — insert — ambiguity — `api_request_timestamp` (and every emitted timestamp) reads the §2.4 logical clock, not wall-clock — `implementation/response.py:14`
- **§2.2** — insert — ambiguity — undefined route → `ERR_INVALID_REQUEST` 404; unsupported method on defined route → `ERR_INVALID_REQUEST` 405 — `implementation/app.py:29-36`
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` rejected `ERR_INVALID_REQUEST`; `created_at` ties broken by creation sequence (legs listing: `sequence_index` ties likewise); filter params are match-only, never validated — `implementation/response.py:56-75`, `implementation/routes/legs.py:43`, `implementation/routes/escorts.py:71-77`
- **§2.4** — insert — ambiguity — clock-set accepts any instant (earlier/equal/later); no monotonicity enforced — `implementation/routes/clock.py:19`
- **§2.5** — insert — ambiguity — `version` starts at 1 at creation with `updated_at` == `created_at` — `implementation/routes/jobs.py:39-42`, `implementation/routes/legs.py:24-27`
- **§2.5** — revise — mismatch — blanket "every modification increments version" qualified with the two silent mirrors (survey-submit clearance mirror; reliability-score maintenance short of suspension) that apply with no version bump or `updated_at` refresh — `implementation/mutate.py:1-9`, `implementation/routes/surveys.py:90-94`, `implementation/routes/incidents.py:170-171`
- **§2.11 item 3** — insert — ambiguity — malformed/non-object JSON body → `ERR_INVALID_REQUEST`; explicit null = missing for required fields, omitted for optional fields — `implementation/util.py:57-76,108-113`
- **§2.11 item 7** — insert — ambiguity — within stage 7, state precondition evaluated before the optimistic-concurrency check (state error surfaces over stale-version error) — `implementation/routes/jobs.py:201-204`, `implementation/routes/surveys.py:111-116`
- **§3.2** — insert — ambiguity — duplicate `sequence_index` permitted; Job representation embeds a `legs` echo of booking-time specs in supplied array order; job listing filterable by `carrier_id`/`job_status` — `implementation/routes/jobs.py:116,131,159-165`, `implementation/serializers.py:100-110`
- **§3.2** — insert — ambiguity — field-less amendment still mutates the job; partial-window amendment validated against the stored counterpart after state/OCC checks (both-supplied pair validated at body-shape time) — `implementation/routes/jobs.py:195-209,235`
- **§3.4** — insert — ambiguity — recording a permit application has no leg-state precondition — `implementation/routes/legs.py:66-95`
- **§3.4** — insert — ambiguity — confirm-police has no leg-state precondition; re-confirming an already-confirmed leg succeeds as a fresh mutation — `implementation/routes/legs.py:53-63`
- **§3.4** — insert — ambiguity — the provisional `survey_min_clearance_inches` mirror at submission does not bump the leg's `version`/`updated_at` — `implementation/routes/surveys.py:90-94`
- **§3.4** — revise — ambiguity — `rejection_reason` must be a non-empty, non-blank string (blank/empty also rejected, not just absent) — `implementation/routes/surveys.py:106-108`
- **§3.5** — insert — ambiguity — selector: identical-`created_at` ties broken by earlier creation; on the selector path the quota check runs before selection (`ERR_POSITION_QUOTA_FILLED` precedes `ERR_NO_ELIGIBLE_ESCORT`) — `implementation/services/cascade.py:196-203`, `implementation/routes/assignments.py:92-98`
- **§3.7** — insert — ambiguity — opening/closing delay events carries no ownership check for `EscortOperator` — `implementation/routes/delays.py:27,74`
- **§3.7** — insert — ambiguity — incident reporting carries no ownership check (any `CarrierRep`/`EscortOperator`); `escort_fault_share_pct` null until first assessment; global incident listing filterable by `assignment_id`/`incident_status` — `implementation/routes/incidents.py:36-57,78,107-113`
- **§3.7** — insert — ambiguity — score update alone is silent (no escort version bump); an already-`SUSPENDED` escort is not re-suspended and the cascade does not re-fire — `implementation/routes/incidents.py:168-173`
- **§3.8** — revise — mismatch — composition applies **no floor** to `total_cents` (was: "the total must never fall below zero"); the zero bound is enforced only by the adjustment guard `ERR_ADJUSTMENT_EXCEEDS_TOTAL` — `implementation/services/calc.py:202-203`, `implementation/routes/invoices.py:166-171`
- **§3.8** — revise — ambiguity — `dispute_reason`/`adjustment_note` required non-empty; adjustment recomputes `total_cents` alone from stored component fields plus the accumulated delta (other components not re-derived from live job data) — `implementation/routes/invoices.py:142,160,166-174`

Everything else walked (all 12 route modules, `services/calc.py`, `services/cascade.py`, serializers, middleware, envelope, error catalog) was already uniquely pinned by the PRD — thresholds, curfew windows, buffering/overlap rule, quote/standby/billing/invoice formulas, cancellation tiers, credit-availability sets, OCC scope, cascade tables, RBAC, and per-endpoint validation orders matched implementation exactly.

# Worklog — task_1549_nonprofit_program_outcome_impact

## Step 1: Create Task Directory — 2026-08-13T20:24:00.000Z

Task directory `tasks/task_1549_nonprofit_program_outcome_impact/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T21:26:00.000Z

All three artifacts generated and lint-clean. Summary:

## Deliverables
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/SCAFFOLD.yaml` (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

## Counts
- Entities: **16** (Program, Funder, LogicModel, Indicator, ProgramCycle, Participant, ConsentRecord, Instrument, TrainingCertification, Observation, Milestone, DataQualityAudit, AuditFinding, Report, VendorEngagement, ImprovementAction)
- State machines: **16** (incl. cyclic LogicModel revision loop, Report DELIVERED→RETURNED→GENERATED rework cycle, ImprovementAction INEFFECTIVE→PROPOSED loop, ProgramCycle close/reopen compensation)
- Calculations: **6** (attainment with PROVISIONAL/FINAL variants + direction/zero-guard/clamp branches; band thresholds; completeness with empty-set→null rule; dq_score with STANDARD/STRICT variants and pinned evaluation order; milestone evaluation with inclusive due boundary; impact index with pinned per-term rounding)
- Validations: **23** ordered priorities (auth → scoping → existence → shape → state → safety(consent) → constraint → temporal → fiscal → OCC-last)
- Endpoints: **109** (includes all FK reverse-reachability GETs and `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Error catalog: **24**
- Roles: **7** (ProgramDirector, EvaluationLead, FieldCollector, DataSteward, PrivacyOfficer opaque; FunderViewer entity_backed:Funder; VendorAnalyst entity_backed:VendorEngagement)
- Difficulty-design instances: **20** (≥2 per rule; 3 for combinatorial_formula covering modes a/b/c, 3 for non_linear_state_machine)
- Corner-design instances: **57 active + 6 excluded_because stubs = 63 total**, across all 9 guide sections

## Notable design decisions
- **Harder-than-expert levers**: segregation-of-duties role model (steward ≠ collector by X-User-ID; proposer ≠ approver across roles); two OCC rules (report-create on ProgramCycle.version, model-approve on Program.version) with supersede semantics making them true races per §1.2.1; dual-variant calculations on two different domains (Indicator attainment vs audit dq_score); a verified rounding-order trap (per-term 49.26 vs sum-then-round 49.25); dq gate boundary where raw 79.999 rounds to a passing 80.00; two interval semantics (closed cycles vs half-open vendor windows × scope intersection).
- All formula-derived asserts were **pre-computed in Python** (80.00/50.00, 85.00/100.00, 75.00/125.00, 49.26, 96.00→100.00, 80.00 gate) before being pinned as literals.
- Consent/certification expiry use **lazy evaluation** (no wall-clock dependence); the logical clock drives milestone due-ness, windows, and late-data flags.
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** — 1002 calls scanned, 0 violations; all 83 instance names unique across both files; every error code is referenced by at least one validation row; forbidden-vocabulary sweep clean.

## Step 3: Copy Shared Files — 2026-08-13T21:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1549_nonprofit_program_outcome_impact/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T21:55:00.000Z

PRD generation is complete and all three hard contracts pass. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/workspace/PRD.md`.

## Summary

**PRD section list** (389 lines, ~8,450 words):
- §1 Introduction (2 paragraphs, pain-point/business-context angle)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (with per-role `identity:` prose: 5 opaque roles, `FunderViewer` entity-backed to `Funder`, `VendorAnalyst` entity-backed to `VendorEngagement`), 2.2 Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties & Version Counter, 2.5 Logical Clock & Lazy Expiry, 2.6 Calendar Windows (closed cycle intervals vs half-open vendor windows), 2.7 Precision & Rounding, 2.8 OCC, 2.9 Validation Order & Segregation of Duties, 2.10 Nested Resource Retrieval
- §3 Business Logic — 9 subsections (3.1 Programs/Funders → 3.9 Vendor Engagements/Improvement Loop)
- §4 Endpoint Definitions: 4-column table, 109 rows (matches scaffold exactly)
- §5 Error Code Catalogue: 2-column table, 24 rows (matches scaffold exactly); document ends here, no audit footer

**Hard contract results:**
- Contract 1 (field-name coverage): 93 required identifiers (entity fields + endpoint inputs/query params), **0 missing**; all 12 computed-output names (`aggregated_value`, `evaluated_count`, etc.) also present. One gap found and fixed during verification (`logic_model_id`).
- Contract 2 (rule coverage): all 23 validations paired with error IDs in prose; both OCC rules fully expressed with exact IDs (`ERR_STALE_CYCLE_VERSION`/`ERR_STALE_PROGRAM_VERSION`, HTTP 412); all state transitions, all 6 calculation formulas, all cross-entity cascades, and all `applies_to` scopes expressed. One gap fixed during verification (finding waive/remediate parent-audit-`OPEN` precondition).
- Contract 3 (§3 path purity): 569 backticked tokens scanned in §3, **0** path/method violations.

**Notable scattering/narration decisions:**
- The observation-recording cascade (7 ordered checks) is rendered as an explicit ordered narrative in §3.6 with earlier-failure-masking semantics; the global validation priority order (auth → scoping → existence → body → state → business → OCC last) lives in §2.9.
- All 6 formulas were translated to reconstruction-safe prose with pinned evaluation orders called out (attainment zero-guard/clamp at 0–150, bands at 90.00/70.00 inclusive-lower-edge, dq weights one-half/three-tenths/one-fifth minus 4.00 per open finding clamped 0–100, per-term rounding pinned for the impact index, DQ report gate at 80.00).
- The three-hop consent-revocation cascade (consent → participant → observations → cycle aggregates) is narrated end-to-end in §3.5; the mutually compensating close-data/reopen-data participant hops are in §3.4.
- Scaffold inconsistency resolved silently: validation #23 names `ERR_STALE_VERSION`, which does not exist in the error catalog; per the skill's OCC rule ("use the exact id the scaffold nominates"), the PRD uses the two catalogued ids from `concurrency_rules` and omits the phantom id.
- One real edit made post-draft: removed an accidentally invented `ERR_ENROLLMENT_WINDOW_OVERLAP` row from §5 (24 rows now match the scaffold catalog exactly).

## Step 5: Generate Unit Tests — 2026-08-13T22:35:00.000Z

Note: the subagent's first run wrote all 9 test_helpers files and conftest.py but stopped before writing test files (turn-limit exit); it was resumed via SendMessage and completed the suite. Final summary verbatim:

Complete. 96 tests total across 13 test files. All 20 difficulty instances have ≥2 tests; all 35 non-stub corner instances except the one deliberate skip have ≥1 test; the 6 `excluded_because` stubs are correctly not emitted.

## Summary

**test_helpers/ files written (9):**
- `test_helpers/__init__.py` — barrel export
- `test_helpers/types.py` — 17 entity TypedDicts, 18 status/enum types, role enum
- `test_helpers/api_client.py` — ApiClient subclass with one method per endpoint from PRD §4 (~65 methods)
- `test_helpers/api_errors.py` — 24 ApiErrorId members + HTTP map registered with framework
- `test_helpers/assertions.py` — assert_{entity} for all 16 entities + common-fields + cycle-aggregate invariants
- `test_helpers/factories.py` — payload factories for all creatable entities
- `test_helpers/constants.py` — dq weights, attainment cap/bands, default timestamps, canonical user ids
- `test_helpers/test_users.py` — TEST_USERS constants + per-instance builders (incl. `make_funder_viewer_headers`/`make_vendor_analyst_headers` for entity-backed roles)
- `test_helpers/fixtures.py` — tiered composite helpers: create_program/funder/cycle, setup_program_with_approved_model, setup_active_cycle, setup_participant_with_consent, setup_observation_world, setup_cycle_under_review, setup_draft/generated/delivered_report, open_audit_for_cycle, record_finding, create_engagement, create_improvement_action, record_and_validate

**test_suite/ files written (14):** conftest.py + 13 test files (test_01..test_13, no test_14 needed).

**Total test count:** 96 (all functions tagged with a `Design:` line)

**Queue-A (Difficulty) coverage:** 20/20 emitted, 0 skipped. Every one of the 20 non-stub difficulty instances has exactly 2 tests, satisfying the ≥2 per instance target. Notably, both `priority_pair_validation_conflict` instances were emitted because PRD §3.6 explicitly states "the domain checks fire **in exactly this order**, each failure masking all later ones. First, ... Second, ..." — giving verbatim coverage for the asserted precedence.

**Queue-B (Corner) coverage:** 35/36 emitted, 1 skipped.
- All 6 `excluded_because:` stubs correctly not emitted (verified cross-reference resolves).
- Skipped: `Corner/state_machines/consent_grant_on_withdrawn_participant_rejected`. Reason: PRD does not uniquely derive that consent grant on a WITHDRAWN participant is rejected — PRD §3.4 states "WITHDRAWN is terminal" but §3.5 (granting consent) lists no participant-status precondition, and §2.9's "child creation is defined" wording doesn't enumerate which states permit consent creation. Two PRD-only readers could plausibly ship both allow and reject variants, so the two-condition filter fails.

**PRD coverage decisions applied:**
- `program_create_defaults_and_retrieval`: softened the literal `version == 1` assertion to `version >= 1` (PRD §2.4 says "mutation counter that increments by exactly one on every modification" but never pins the initial value; two readers could ship 0 or 1). All other asserts (DRAFT, cfv=1, null model) are verbatim PRD-covered.
- All other assertions are PRD-verbatim covered and uniquely derivable.

## Step 6: Generate Implementation — 2026-08-13T22:45:00.000Z

All 109 endpoints are implemented with none missing or extra, and the full behavior suite passes. Implementation is complete.

## Summary

**Task**: `task_1549_nonprofit_program_outcome_impact` — complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/workspace/implementation/`.

### File list
- `start.sh` — executable launcher; guarded dependency install (`import flask` check, so per-test reboots skip pip), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — app factory, Decimal-aware JSON provider, envelope-wrapped error handlers (ApiError/404/405/500), blueprint registration
- `db.py` — in-memory `Store` (16 entity dicts, empty at boot, no seeding), logical clock (startup default `2026-08-01T00:00:00Z`), ISO-8601 parse/format with 3 fractional digits
- `errors.py` — `ApiError` + the 24-entry error catalog
- `response.py` — envelope helpers: `meta{api_request_id (req_*), api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `require_roles` decorator enforcing auth priorities 1–3 (headers → known role → endpoint role)
- `util.py` — body parsing (`parse_float=Decimal`), typed field validators, pagination (limit default 10, clamped [1,100]; offset ≥ 0), `created_at`-ascending sort with insertion-sequence tiebreak, `touch()` OCC-style version bump (once per entity per request), serializer dropping `_`-internal fields
- `services.py` — lazy expiry, consent_status derivation, revocation/withdrawal cascade, cycle aggregates, dq_score (STANDARD/STRICT), attainment, impact index
- `routes/`: `core.py` (clock, programs, funders), `models.py` (logic models, indicators, attainment), `cycles.py` (cycle lifecycle, milestones, evaluate batch, dashboard), `people.py` (participants, consents), `instruments.py` (instruments, certifications), `observations.py`, `quality.py` (audits, findings), `reports.py`, `vendors.py`, `improvements.py`

### Coverage
- **Endpoints**: 109/109 from the PRD §4 table (verified programmatically against the URL map)
- **State machines**: all 15 implemented with preconditions and side effects — Program, Funder, LogicModel (incl. approve's supersede/retire/activate cascade + program version bump), Indicator, ProgramCycle (incl. close/reopen participant compensation), Participant (incl. consent-grant auto-activation and 3-state withdrawal cascade), ConsentRecord (supersede/revoke/lazy-expire), Instrument (publish hand-off retiring predecessor + staling its certifications), TrainingCertification, Observation, Milestone, DataQualityAudit, AuditFinding, Report (incl. DRAFT/GENERATED supersede-on-create and RETURNED→GENERATED rework), VendorEngagement, ImprovementAction (incl. VERIFIED_INEFFECTIVE→PROPOSED loop)
- **Calculations**: all 6 — indicator_attainment (zero-guard → direction branch → clamp [0,150] → round; PROVISIONAL/FINAL input sets), attainment_band (inclusive 90/70 edges), data_completeness_pct (null when eligible/active sets empty), dq_score (pinned evaluation order; 0.5C+0.3V+0.2K−4F; STRICT variant drops late observations from V), milestone_evaluation (inclusive due_date boundary), overall_impact_index (per-term rounding pinned before summation, weight renormalization). All arithmetic in `Decimal`, round-half-up at 2dp
- **OCC**: `expected_program_cycle_version` (report create) and `expected_program_version` (model approve), checked last per priority 23

### Notable decisions
- **PRD-over-scaffold conflict**: scaffold `validations[23]` lists `ERR_STALE_VERSION`, but PRD §2.8/§5 and the concurrency_rules table declare `ERR_STALE_CYCLE_VERSION` / `ERR_STALE_PROGRAM_VERSION` — implemented the PRD error IDs.
- **Version semantics**: `version` starts at 1; each entity bumped at most once per request (per-request dirty set), so compound operations (e.g., consent grant that activates) bump the participant once; aggregate recomputes bump only on actual change. Cycle version advances on report creation and on every aggregate mutation, which the report OCC check then observes.
- **Certification staleness**: since `instrument_version` never mutates on an entity (revisions are new entities), staleness is evaluated against the code line's current version (max version among PUBLISHED/RETIRED revisions — drafts don't advance the line), applied both at reinstate (`ERR_CERTIFICATION_STALE`) and at observation recording.
- **Scope fails closed**: FunderViewer single-report access to a nonexistent or foreign report yields `ERR_SCOPE_DENIED` (scope priority 4 masks existence priority 5); VendorAnalyst checks engagement existence → ACTIVE → half-open window `[access_start, access_end)` → scope membership before target reads.
- **Observation-recording FK nonexistence folds into the business checks** (nonexistent instrument → `ERR_INSTRUMENT_NOT_PUBLISHED`; indicator → `ERR_INDICATOR_NOT_IN_MODEL`), matching the scaffold's ordered check list; other body FKs (funder, finding participant/indicator/observation, certification instrument, improvement-action links) return 404.
- **Input datetimes echoed verbatim** in responses; parsed copies used for all comparisons. Clock set echoes `to_iso8601` as supplied.
- **Revocation cascade withdraws only ENROLLED/ACTIVE/EXITED participants** (COMPLETED participants are untouched per the Participant machine), excluding their PENDING/VALIDATED/FLAGGED observations with `exclusion_reason=CONSENT_REVOKED` and recomputing cycle aggregates + audit dq.
- Verified boot contract: `start.sh` on `$PORT`, 0.0.0.0, foreground; kill/restart yields an empty store (per-test-server isolation safe).

## Step 7: Run Tests and Iterate — 2026-08-13T23:05:00.000Z

All 8 rounds pass: 96/96 each, zero failures. The sweep is clean.

## Summary

**Iterations run:** 2 (initial sweep → fixes → clean 8-round sweep)

**Initial state:** 3 deterministic failures, identical across all 8 rounds (no flakiness):
1. `test_02…::test_revision_loop_reopens_indicator_edits` — 409 `ERR_INVALID_STATE: Logic model in state SUBMITTED cannot transition to SUBMITTED`
2. `test_03…::test_close_and_reopen_data_compensates_participants` — 409 `ERR_INVALID_STATE: Cycle in state ENROLLING cannot transition to DATA_CLOSED`
3. `test_06…::test_indicator_outside_pinned_model_rejected` — `NameError: name 'create_indicator' is not defined`

**Tests deleted:** none. All three assert rules verbatim-covered and uniquely derivable from PRD §3.2/§3.4/§3.6 (revision loop reopens edits; close moves `ACTIVE → DATA_CLOSED` with participant compensation; indicator must belong to the cycle's pinned model else `ERR_INDICATOR_NOT_IN_MODEL`).

**Fixes to `test_suite/`** (all STEP 2 test bugs — PRD-inconsistent setups; the implementation was correct to reject them):
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/test_suite/test_02_logic_models_and_indicators.py` — the test submitted the model itself, then called the `approve_logic_model` fixture whose contract is "submit + approve from DRAFT"; the fixture's re-submit tripped the state gate. Replaced with the explicit get-program-version + approve pattern already used elsewhere in the same file.
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/test_suite/test_03_cycles_and_participants.py` — setup called `close_data` on an ENROLLING cycle under a program with no approved logic model, violating PRD §3.4 ("closing data moves `ACTIVE → DATA_CLOSED`"; activation "requires … an approved logic model"). Rebuilt setup via `setup_program_with_approved_model` + `setup_active_cycle` (the file's own established pattern); assertions unchanged.
- `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/test_suite/test_06_observations.py` — added missing `create_indicator` to the `test_helpers.fixtures` import block.

**Fixes to `test_helpers/`:** none. **Fixes to `implementation/`:** none — the implementation was PRD-faithful in all three cases.

**Final state:** 8/8 parallel rounds green, 96 passed / 0 failed / 96 total per round.

## Step 8: Finalize PRD — 2026-08-13T23:15:00.000Z

Done. PRD_FINALIZED.md was produced as an unchanged copy of PRD.md — all three step_7_diff items turned out to be pure test-side bugs with zero PRD silence or mismatch at their implementation sites.

**Line counts / delta:** PRD.md = 388 lines; PRD_FINALIZED.md = 388 lines; 0% delta (zero edits).

**Per-item verification (each item's subject, impl paths enumerated, and why no edit was committed):**

1. **`test_02::test_revision_loop_reopens_indicator_edits`** — subject: logic-model submit/revise state gating and indicator-edit gating.
   - Impl paths enumerated: `routes/models.py:91-102` (`submit_logic_model` — `_model_transition(mid, ("DRAFT",), "SUBMITTED")`, then ≥1-indicator check), `models.py:151-158` (`reject_logic_model`, `SUBMITTED → REJECTED`), `models.py:161-167` (`revise_logic_model`, `REJECTED → DRAFT`), `models.py:202-234` (`create_indicator` requires model `DRAFT`), `models.py:255-281` (`patch_indicator` requires model `DRAFT`).
   - The 409 (`SUBMITTED cannot transition to SUBMITTED`) came from the fixture re-submitting an already-submitted model. PRD §3.2 already pins the workflow verbatim ("runs `DRAFT → SUBMITTED → APPROVED`… revision moves `REJECTED → DRAFT`, reopening the model and its indicators for editing"; "once the model leaves `DRAFT`, indicator edits are rejected with `ERR_INVALID_STATE`"), and §2.9's state-gate step makes submit-from-non-DRAFT rejection uniquely derivable. No PRD silence — no edit.

2. **`test_03::test_close_and_reopen_data_compensates_participants`** — subject: cycle close/reopen state gating and participant compensation.
   - Impl paths enumerated: `routes/cycles.py:203-216` (`close_data` requires `ACTIVE`; `ACTIVE → COMPLETED` hop; `recompute_cycle_aggregates`), `cycles.py:219-232` (`reopen_data` requires `DATA_CLOSED`; `COMPLETED → ACTIVE`), `cycles.py:180-200` (`activate_cycle` requires program `ACTIVE` and `current_logic_model_id` non-None), `services.py:142-157` (aggregate recompute), `services.py:39-40` (`cycle_participants`).
   - The 409 came from the test calling `close_data` on an `ENROLLING` cycle under a program with no approved model. PRD §3.4 pins all of it verbatim ("closing data moves `ACTIVE → DATA_CLOSED`, and every participant still `ACTIVE` hops to `COMPLETED`… reopening moves `DATA_CLOSED → ACTIVE` and compensates exactly…"; "Activation requires the program to be `ACTIVE` and to have an approved logic model; without one, the request is rejected with `ERR_INVALID_STATE`"; "Every transition into or out of the wrong state is `ERR_INVALID_STATE`"). No PRD silence — no edit.

3. **`test_06::test_indicator_outside_pinned_model_rejected`** — subject: pinned-model indicator check on observation recording.
   - Impl paths enumerated: `routes/observations.py:54-65` (check #4: indicator must be `ACTIVE` and `logic_model_id == cycle["pinned_logic_model_id"]`, else `ERR_INDICATOR_NOT_IN_MODEL` 422), plus the parallel milestone-definition check at `routes/cycles.py:295-305` using the same predicate and error.
   - The failure was a `NameError` (missing `create_indicator` import in the test) — no behavioral content at all. The underlying rule is verbatim-covered by PRD §3.6 ("Fourth, the indicator must be `ACTIVE` and belong to the cycle's pinned logic model, else `ERR_INDICATOR_NOT_IN_MODEL` (HTTP 422)") and §3.8 for milestones. No PRD silence — no edit.

**Pre-edit search log:** no edits were committed, so there are no (a)/(b)/(c) entries to report; the enumerations above document the per-item site inspections that established "pure test bug" for all three.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/workspace/PRD_FINALIZED.md` (byte-identical to PRD.md). Explicitly stating per the allowed outcome: the step_7 diff items are pure test-side bugs — the implementation was PRD-faithful at all three sites and the PRD already uniquely determines each asserted behavior.

## Step 9: Complete PRD — 2026-08-13T23:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1549_nonprofit_program_outcome_impact/workspace/PRD_COMPLETED.md` written.

**Source**: PRD_FINALIZED.md (388 lines, 61,323 chars) → PRD_COMPLETED.md (391 lines, 67,074 chars; +5,751 chars). No new sections; all changes are in-paragraph inserts/revisions plus one error-catalogue row.

**Counts**: 41 changes total — 32 ambiguity-pins, 9 mismatch-revisions.

**Mismatch-revisions (9)**:
- §2.3 — revise — mismatch — out-of-range `limit`/`offset` are clamped to bounds, not rejected; non-integer values → `ERR_INVALID_REQUEST` — implementation/util.py:145-165
- §3.3 — revise — mismatch — certification version checks compare against the *instrument line's* current version (max `instrument_version` among same program+code revisions in `PUBLISHED`/`RETIRED`), since a record's own `instrument_version` never advances — implementation/services.py:52-64
- §3.4 — revise — mismatch — enrollment domain checks fire state → window → uniqueness (PRD prose order implied uniqueness first under §2.9's "order stated" rule) — implementation/routes/people.py:42-59
- §3.5 — revise — mismatch — `consent_status` derivation pinned exactly: with no `GRANTED` record it is `EXPIRED` when any record stands `EXPIRED` or `SUPERSEDED` with a trailing form version (PRD said superseded-without-replacement → `NONE`) — implementation/services.py:75-110
- §3.5 — revise — mismatch — revocation recomputes `consent_status` per the derivation rule, not unconditionally to `NONE` — implementation/routes/people.py:213-224
- §3.6 — revise — mismatch — observation check six compares `certified_instrument_version` to the line's current version, not the instrument record's own version — implementation/routes/observations.py:80-89
- §3.6 — revise — mismatch — flag `reason` is required but validated-and-not-persisted (PRD said "records the steward's reason"; no such field exists) — implementation/routes/observations.py:212-228
- §3.7 — revise — mismatch — `observation_id` null for `MISSING_DATA` findings is not enforced — implementation/routes/quality.py:128
- §5 — revise — mismatch — added `ERR_INTERNAL` | 500 row (catalogue claimed to enumerate every error id; app.py:39-41 raises it)

**Ambiguity-pins (32)**: §2.1 empty-valued header counts as missing (middleware.py:31); §2.1 scoping fails closed → `ERR_SCOPE_DENIED` not 404 for unverifiable targets (reports.py:26-33, observations.py:124-132, cycles.py:25-40); §2.2 `api_request_timestamp` read from the logical clock (response.py:13); §2.2 unrouted paths/405 → `ERR_NOT_FOUND`, unexpected failures → `ERR_INTERNAL` 500 (app.py:31-41); §2.3 `created_at` ties broken by creation order (util.py:168-170); §2.3 `has_more` = offset+returned < total_count (response.py:26); §2.4 `version` starts at 1 (db.py:72-84); §2.4 at most one version bump per entity per request, no-change recompute no bump (util.py:186-199, services.py:142-162); §2.5 all server timestamps from the logical clock and `current_utc` echoes the supplied string verbatim (db.py:55-60, core.py:26-33); §2.5 which reads trigger lazy expiry (participant fetch/consent-history; cert fetch/list; cert list filters on stored status before refresh; participants-of-cycle list does not refresh) (people.py:86-91,186-196, instruments.py:179-201); §2.9 absent body = {}, malformed/non-object JSON → `ERR_INVALID_REQUEST` (util.py:41-52); §2.10 body-referenced ids resolve after well-formedness/before state, `ERR_NOT_FOUND`, with the §3.6/§3.8 domain-error exceptions (quality.py:130-135, reports.py:45-47, improvements.py:34-37); §3.1 program and funder `code` must be non-empty (core.py:42,159); §3.2 indicator `code` non-empty, non-positive `weight` → `ERR_INVALID_REQUEST`, patched code must stay unique (models.py:182,195-196,266-277); §3.2 attainment: missing `program_cycle_id`/bad `variant` → 400 (models.py:299-306); §3.3 instrument creation imposes no code uniqueness, always version 1 (instruments.py:26-43); §3.3 new-revision inherits `title`, allowed from any status (instruments.py:101-116); §3.3 certification create: unknown instrument → 404, non-PUBLISHED → `ERR_INVALID_STATE` (instruments.py:156-162); §3.3 reinstatement ignores `expires_at` (instruments.py:221-244); §3.4 re-enroll violations → `ERR_INVALID_STATE` (people.py:122-131); §3.5 granting not gated on participant status, past-due grant flips to `EXPIRED` in-request, never resurrects `WITHDRAWN` (people.py:141-183); §3.6 multiple collector-instrument certs → most recently created governs (observations.py:66-79); §3.7 finding references must exist, `description` defaults empty (quality.py:126-135); §3.8 unknown milestone `indicator_id` → `ERR_INDICATOR_NOT_IN_MODEL` not 404 (cycles.py:295-305); §3.8 milestone evaluation has no cycle-state precondition and does not re-check indicator status (cycles.py:338-376); §3.8 return `reason` required but not persisted (reports.py:217-232); §3.8 FunderViewer restriction applies to both report lists, supplied `funder_id` filter ignored (reports.py:93-132); §3.9 scope cycle ids not validated for existence (vendors.py:30); §3.9 deliverable `note` required but not persisted (vendors.py:154-158); §3.9 improvement-action creator id stored internally, never serialized (improvements.py:49, util.py:181-182).

No implementation behavior was invented; every pin traces to the cited file:line.

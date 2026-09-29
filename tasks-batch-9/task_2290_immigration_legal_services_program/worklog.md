# Worklog — task_2290_immigration_legal_services_program

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2290_immigration_legal_services_program/` and `tasks/task_2290_immigration_legal_services_program/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T15:35:00.000Z

Orchestrator note: the first single-subagent attempt at Step 2 was terminated by the API for exceeding the 64000-output-token per-response cap (it tried to emit the whole scaffold in one Write). Step 2 was therefore re-run as three subagents with a mandatory incremental-write protocol: 2a produced `SCAFFOLD.yaml`, then 2b (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`) and 2c (`SCAFFOLD_CORNER_DESIGN.yaml`) ran concurrently reading only `SCAFFOLD.yaml`. All three files `yaml.safe_load` cleanly with the expected top-level keys.

### Step 2a — SCAFFOLD.yaml (subagent summary, verbatim)

SCAFFOLD.yaml is complete and validated.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2290_immigration_legal_services_program/SCAFFOLD.yaml` — 4141 lines, single file, parses cleanly under `yaml.safe_load`.

**Top-level keys (13):** `api_prefix`, `calculations`, `complexity_profile`, `concurrency_rules`, `domain_name`, `endpoints`, `entities`, `errors`, `response_envelope`, `roles`, `scenario`, `state_machines`, `validations`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.

**Counts**

| Section | Count |
|---|---|
| §1.1 entities | 15 (32 FKs) |
| §1.2 state machines | 11 |
| §1.2.1 concurrency rules | 3 (all OCC on a parent `version`) |
| §1.3 calculations | 18 (incl. 2 dual-variant, 3 conservation invariants) |
| §1.4 validations | 39 (priorities 1–39, 4 declared conflict pairs) |
| §1.5 endpoints | 63 |
| §1.6 errors | 56 |
| §1.7 roles | 6 |

**Entities:** Client, ProgramCapacityCycle, DetentionFacility, OrganizationRecognition, Representative, Accreditation, IntakeScreening, CaseMatter, CaseAssignment, EvidenceItem, Declaration, InterpretationSession, CalendarEvent, InformedDecision, GrantReport.

**Roles:** ProgramDirector (opaque), IntakeScreener (entity_backed:Representative), SupervisingAttorney (entity_backed:Representative), CaseRepresentative (entity_backed:Representative), GrantAnalyst (opaque), ClientPortalUser (entity_backed:Client).

**Consistency checks run and passing**
- FK reverse-reachability: 0 `FK_REVERSE_UNREACHABLE` (every one of the 32 FKs, including the four self-referential ones, is an optional query param on its child's filtered-list GET).
- Every §1.2 `trigger:` resolves to a declared §1.5 path/method; every §1.2 `actor:` and every §1.5 `roles:` entry is one of the 6 §1.7 roles.
- Error catalog closed both ways: 0 referenced-but-uncatalogued, 0 catalogued-but-unreferenced. Schemas exact (`id`/`http`/`condition`; `name`/`description`/`identity`/`exclusive_operations`/`shared_operations`).
- All 3 OCC endpoints carry `expected_*_version` in `input:` and a version increment in `side_effects:`; no forbidden concurrency vocabulary ("simultaneous", "in parallel", "first-writer-wins", etc.) anywhere in the file.
- All `applies_to` endpoint references resolve to declared paths; all entity/field references in §1.6 and §1.7 resolve to §1.1 fields or endpoint inputs.

**Issues found and fixed this session**
- 41 endpoint `input:` flow lists contained bare `field?` tokens, which PyYAML rejects (`expected ',' or ']', but got '?'`) even though SKILL.md §1.5 writes them unquoted. Optional markers are now quoted (`"a_number?"`), preserving the `?` semantics for `scaffold_lint.py` check (c)/(f).
- Validation priority 15 gated on `representation_status != 'CLOSED_OUT'`, a state CaseMatter never declares; narrowed to `!= 'WITHDRAWN_FROM'`.
- Two Accreditation transitions had prose-only triggers (`system event: ...`); rewritten to name the `POST /organization-recognitions/{recognition_id}/transition` cascade hop so downstream setup chains can reach those states.
- Three catalog orphans left by the earlier §1.5 rewrite: `ERR_MATTER_ALREADY_EXISTS` was dropped as redundant with `ERR_INVALID_STATE_TRANSITION`; `ERR_DERIVATIVE_CLIENT_MISMATCH` and `ERR_LEAD_NOT_ASSIGNED` were tied to their triggering endpoints via validations 16 and 24.
- `disclosure_mode` → `disclosure_level` in the GrantAnalyst role description.

### Step 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (subagent summary, verbatim)

Done. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete and validated.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2290_immigration_legal_services_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml`

- **Rule groups: 9** (all nine §0.5 `rule_id`s, in order)
- **Total instances: 20** — `priority_pair_validation_conflict` and `compensating_invariant` carry 3 each, the other seven carry 2 (min is ≥2 / ≥18 total)
- **Non-stub instances: 20 / 20** — every instance has fully worked `setup`, structured `setup_api_calls`, structured `trigger`, and literal `assert` lines (441 structured API calls, 141 assertions total)
- **Final line count: 2440**
- Validation: `python3 -c "import yaml; ..."` → `['scaffold_difficulty_design']`, no parse errors.
- Only that one file was created. `SCAFFOLD.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never written to (corner design is the concurrent agent's, and it did land its own file).

## Coverage of the "harder than expert" mandate
Differentiation clauses honored: two entity domains (urgency vs filing-readiness), two formula modes (per-session-then-sum rounding vs pinned tier-then-largest-remainder), two entities' cycles (matter representation revert-cycle, accreditation renewal cycle), two depth-4 cascades from different triggers (recognition LAPSE, accepted-intake WITHDRAW), three distinct error-category pairs (business_safety vs business_fiscal, existence vs state, auth vs existence), two metric kinds at both endpoints (rounded FPL percent ±1 cent; integer per-date slot aggregate incl. the degenerate 0 ceiling plus a 1 ms lead-time seam), two disjoint entity pairs (Declaration←InterpretationSession, CaseAssignment←OrganizationRecognition), two interval semantics on different resources (representative half-open + location-dependent travel buffer vs client fully-closed across matters with the FILING_DEADLINE exemption), three conserved quantities (slot partition, caseload/supervisee counters, grant money allocation).

## Verification notes worth relaying
- All arithmetic was recomputed with Python (Decimal/Fraction), and a mini-lint pass over the finished file confirmed: every endpoint+method exists in §1.5, every `as:` role is in that endpoint's `roles`, every `payload:` key is in that endpoint's `input:`, every `captures:` field exists on the endpoint's `output:` entity, every `${var}` (in calls, headers and asserts) is bound by an earlier `captures:`, and every `grounds` ref resolves. The single intentional role violation is the CONFLICT PAIR 1 probe (ClientPortalUser → `POST /case-assignments`), which is the point of that instance.
- Three modeling corrections made during authoring: `fpl_percent` lives on `Client` (2 dp) and the verdict is `IntakeScreening.legal_eligibility_verdict`, not an `eligibility_flag`; detention facilities must use a `SERVED_JURISDICTIONS` code (`TX-ELP`/`AZ-ELO`) or detained intakes screen `INELIGIBLE_JURISDICTION`; and because p35 lists `POST /intake-screenings` in `applies_to`, the over-ceiling client is registered compliant and pushed over the line by `PATCH /clients` after its intake exists, so the recipe never depends on whether the ceiling can fire at creation time.
- CONFLICT PAIR 3 (p18 `ERR_MATTER_NOT_READY` vs p24 `ERR_FORUM_NOT_AUTHORIZED`) is unreachable in this scaffold — a LEAD lacking the matter's forum can never be ACTIVATED, and no endpoint narrows a recognition's `authorized_forums` — so PAIRs 4, 2 and 1 were used instead. That is a genuine gap in SCAFFOLD.yaml's declared pair list if the pipeline expects all four pairs to be testable.

### Step 2c — SCAFFOLD_CORNER_DESIGN.yaml (subagent summary, verbatim)

Done. `SCAFFOLD_CORNER_DESIGN.yaml` is complete and clean.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2290_immigration_legal_services_program/SCAFFOLD_CORNER_DESIGN.yaml` (the only file written; SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml untouched).

**Sections emitted (all 9 §1.9 sections, taxonomy closed — no invented `section:`/`claim_type:` names):**

| section | instances |
|---|---|
| entities | 16 |
| state_machines | 29 |
| calculations | 18 |
| validations | 12 |
| endpoints | 9 |
| errors | 9 |
| rbac | 6 |
| cross_cutting_complexity_layers | 4 |
| consistency_model | 2 |

**Totals:** 105 instances, 105 non-stub (zero `excluded_because:` stubs), 6907 lines.

**Validation results (final run):**
- `yaml.safe_load` parses; single top-level key `scaffold_corner_design`.
- `unbound: []` — every `${var}` in every `setup_api_calls`/`trigger` entry is bound by an earlier `captures:` or by a named setup macro (TEMPLATE A / ACCEPT_INTAKE / TEMPLATE B, defined in the file's header comment).
- 0 duplicate instance names; all 105 instances carry all four `test_recipe` keys (`setup`, `setup_api_calls`, `trigger`, `assert`).
- Error-catalog coverage: all 40 distinct `error_id` values declared in SCAFFOLD.yaml appear as asserted outcomes — `MISSING: []`.

**Final cleanup applied this run (the two outstanding placeholder-closure defects):**
- `err_invariant_violation_never_fires_because_the_three_conservation_assertions_hold` — added a `captures:` line to the macro-expansion call binding `rec_id`, `nadia_id`, `omar_id`, `nadia_acc_id`, `omar_acc_id`, `nadia_lead_id`, `omar_lead_id`, `m2_id`.
- `conflict_pair_3_matter_not_ready_beats_forum_not_authorized_and_lead_absence_preempts_both` — the `${fac_id}` reference was a self-reference inside the very call that created the facility, so the prose was rewritten to name the facility inline rather than adding a forward-bound placeholder.

Anchors were re-located by content rather than by cached line numbers, which is what had aborted the two prior patch attempts.

**Breadth highlights for an `expert_plus` corner design:** every §1.5 endpoint family is exercised (including an explicit instance recording that no bulk endpoint exists, so multi-row effects arrive only via cascades); all 39 rows of the §1.4 priority ladder are represented, with dedicated priority-collision instances proving e.g. priority 2 (role) precedes path-id resolution, priority 16 outranks the derivative-link gate, priority 18 outranks priority 24, and the 412 OCC checks run last; all three §1.2.1 `concurrency_rules` get stale-token instances; the `segregation_of_duties` role model gets all three SoD pairs plus the ProgramDirector `identity: opaque` consequence; and the `dual_variant_calculation` layer contrasts a variant frozen at screen time against one that re-selects on every read.

Known SCAFFOLD.yaml internal contradictions were sidestepped rather than silently resolved, and are flagged inline in the YAML: ERR_FORUM_NOT_AUTHORIZED vs ERR_FORUM_GRANT_EMPTY, ERR_FACILITY_LEAD_TIME_NOT_MET vs ERR_FACILITY_CREDENTIAL_EXPIRED, `ACCREDITED_REPRESENTATIVE` (§1.4) vs `ACCREDITED_REP` (§1.1 enum), `Client.status` PROSPECTIVE vs {ACTIVE, CLOSED}, and §1.7 listing `POST /accreditations/{id}/transition` as ProgramDirector-exclusive while §1.3 stores a SupervisingAttorney's X-User-ID in `approved_by_representative_id`. These are worth a look before the scaffold is used to generate the PRD.

## Step 3: Copy shared files — 2026-09-01T15:36:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2290_immigration_legal_services_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:02:00.000Z

Verification complete. All checks pass after the final round of corrections.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2290_immigration_legal_services_program/workspace/PRD.md` — **525 lines**, 16,529 words. No stray heredoc delimiters, no duplicated or truncated chunks, no `MDEOF` residue, no fuzzy quantifiers (the four `about` occurrences are prepositional: "learns nothing about", "reasoned about", "a fact about", "counseling about").

## Section list

§1 Introduction · §2 Global Specifications (2.1 Actors & RBAC, 2.2 API Response Structure *verbatim block*, 2.3 Pagination & List Ordering, 2.4 Common Properties / Versioning / Logical Clock, 2.5 Numeric Precision & Rounding, 2.6 Path Resolution & Reference Integrity, 2.7 Rejection Ordering, 2.8 Stale-Version Guards, 2.9 Conserved Quantities & Post-Write Assertions, 2.10 Client Confidentiality Scopes) · §3 Business Logic (3.1 Registration/Household/Indigency, 3.2 Capacity Cycles & Two Slot Pools, 3.3 Screening: Eligibility & Two Urgency Geometries, 3.4 Decision Fork / Slot Waterfall / Waitlist, 3.5 Recognition, Accreditation & Derived Authority, 3.6 Staffing / Supervision Selection / Hours, 3.7 Evidence, Declarations & Interpretation, 3.8 Detention Facilities & Three Calendar Geometries, 3.9 Informed Decisions & Filing Dimension, 3.10 Cascades / Checkpoint Sweep / Funder Reporting) · §4 API Endpoint Definitions (4-column table, 63 rows) · §5 Error Code Catalogue (2-column table, 56 rows).

## Hard-contract verification

- **Contract 1 — Field-Name Coverage: PASS.** Entity fields 170 required / 170 present / 0 missing. Endpoint `input` + `query_params` identifiers 121 / 121 / 0. Path params 15 / 15 / 0 (a 16th match, `9`, is the quantifier in the `a_number` regex `^A[0-9]{9}$`, not a path param).
- **Contract 2 — Rule Coverage: PASS.** 39 validations with their priority bands and all four competing-complaint pairs; 3 OCC guards each naming endpoint + version field + error id + 412; 69 transitions across 11 state machines including every system-actor edge (checkpoint-driven `EXPIRING`/`EXPIRED`, cascade-driven `SUSPENDED_BY_RECOGNITION` and its reinstatement, create-time `DOCUMENTED → SUPERSEDED`, cascade-driven declaration and calendar-event edges); 15 calculations + 3 invariants; all 56 error ids present in prose.
- **Contract 3 — §3 Path Purity: PASS.** 1,559 backtick tokens in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations.

Cross-checks against the scaffold: the §5 table reproduces all 56 error ids in scaffold order with byte-identical HTTP statuses; the §4 table reproduces all 63 endpoints in scaffold order with identical methods, paths, and role sets.

## Corrections made in this final pass

- §3.8 reschedule ceiling: replaced a self-contradictory sentence with "three reschedules succeed, leaving the counter at 3, and the fourth attempt is refused."
- Six §4 filter descriptions that had drifted from the actual `query_params`: capacity cycles (posture only, no label), recognitions (status only, no recognition number), representatives (added spoken language), accreditations (added approving attorney), evidence items (tier/status/translation requirement, not item type), declarations (added preparer, reviewer, read-back session).

## Scaffold internal inconsistencies adjudicated

1. `POST /clients` side effect says `status = 'PROSPECTIVE'`; enum is `{ACTIVE, CLOSED}` default `ACTIVE` → **`ACTIVE`**.
2. `POST /intake-screenings` says `legal_eligibility_verdict = null`; entity default is `PENDING` and `null` is not in the enum → **`PENDING`**.
3. Validations 20 and 22 write `rep_type == 'ACCREDITED_REPRESENTATIVE'`; enum value is `ACCREDITED_REP` → **`ACCREDITED_REP`**.
4. Priority 11 references `representation_status` `'CLOSED_OUT'`, which does not exist; paired rule uses `WITHDRAWN_FROM` → **`WITHDRAWN_FROM`**.
5. `ERR_INTAKE_NOT_ACCEPTED` condition lists a `SCREENING` status absent from the enum → **omitted**.
6. `IntakeScreener` role text names `screened_by_representative_id`; the field is `screener_representative_id` → **field name used**.
7. `POST /interpretation-sessions` sets `billed_minutes = null`; entity default is `0` → **`0`**.
8. `accreditation_forum_grant` says an empty intersection raises `ERR_FORUM_NOT_AUTHORIZED`; the endpoint and the dedicated catalog entry use `ERR_FORUM_GRANT_EMPTY` → **`ERR_FORUM_GRANT_EMPTY`**.
9. Priority 18 implies `FILED` is reachable only from `READY_TO_FILE`; the state machine allows `READY_TO_FILE` and `RFE_PENDING` → **state machine wins**.
10. `PATCH /representatives/{representative_id}` and `ERR_REPRESENTATIVE_INACTIVE` mention `'SEPARATED'`; enum is `{ACTIVE, INACTIVE, SUSPENDED}` → **`INACTIVE`/`SUSPENDED`**.
11. Priority 20 calls a recognition `SUSPENDED`; recognition statuses are `{ACTIVE, CONDITIONAL, LAPSED, WITHDRAWN}` → rendered as **"outside `{ACTIVE, CONDITIONAL}`"**.
12. `checkpoint_epoch` / `last_checkpoint_utc` field notes say 0 / null before the first sweep, but `POST /capacity-cycles` sets 1 and the logical clock → **endpoint wins**.
13. `interpreter_required`, client `status` on PATCH, and `requires_translation` are declared endpoint inputs yet computed → documented as **accepted but always derived, contradicting values never honoured**.
14. `Declaration.word_count` is `>= 1` in the entity but optional at creation → **optional at creation, at least 1 when supplied**.
15. EvidenceItem, Declaration, InterpretationSession, CalendarEvent and InformedDecision have list endpoints but no single-resource GET → documented that **the list is the only read channel**.
16. `POST /representatives` marks `max_case_load` / `max_supervisees` / `weekly_capacity_hours` required while the entity declares defaults 25 / 10 / 40.00 → **supplied at creation, those figures described as conventional**.
17. `POST /informed-decisions` attributes empty `risks_disclosed` / `alternatives_disclosed` to `ERR_CONSENT_SCOPE_INSUFFICIENT` rather than `ERR_VALIDATION` → **endpoint text followed**.
18. `ERR_XXX` appears only inside a scaffold doc comment as an envelope placeholder → **excluded from §5**.

Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T18:55:00.000Z

Final file created this session: `/home/ubuntu/github/CodingPRD/tasks/task_2290_immigration_legal_services_program/test_suite/test_corner_state_machines_recognition.py` (5 tests) — the recognition/accreditation/grant-report tail of §1.9 `state_machines`.

## Deliverables

Infrastructure — `test_helpers/`: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`; plus `test_suite/conftest.py`.

Test suite — `test_suite/` (tests / design instances):

| file | tests | instances |
|---|---|---|
| test_difficulty_dual_variant_calc.py | 4 | 2 |
| test_difficulty_combinatorial_formula.py | 4 | 2 |
| test_difficulty_non_linear_state_machine.py | 2 | 1 |
| test_difficulty_transitive_cascade.py | 4 | 2 |
| test_difficulty_priority_pair_validation_conflict.py | 5 | 3 |
| test_difficulty_boundary_precision_check.py | 4 | 2 |
| test_difficulty_cross_entity_state_dependency.py | 2 | 1 |
| test_difficulty_resource_temporal_overlap.py | 4 | 2 |
| test_difficulty_compensating_invariant.py | 6 | 3 |
| test_corner_consistency_model.py | 3 | 2 |
| test_corner_cross_cutting_complexity_layers.py | 8 | 4 |
| test_corner_rbac.py | 10 | 5 |
| test_corner_endpoints.py | 15 | 9 |
| test_corner_errors.py | 14 | 9 |
| test_corner_entities.py | 16 | 16 |
| test_corner_validations.py | 11 | 11 |
| test_corner_calculations.py | 18 | 18 |
| test_corner_state_machines_intake.py | 12 | 12 |
| test_corner_state_machines_matter.py | 7 | 7 |
| test_corner_state_machines_calendar.py | 4 | 4 |
| test_corner_state_machines_recognition.py | 5 | 5 |

**Total 158 tests. `python3 -m pytest --collect-only -q` → 158 tests collected in 5.34s.** `python3 -m compileall test_suite test_helpers` OK; `python3 -m pyflakes test_suite test_helpers` silent.

## Design-index coverage
125 non-stub instances exist (queue A 20; queue B 105 = state_machines 29, calculations 18, entities 16, validations 12, endpoints 9, errors 9, rbac 6, cross_cutting 4, consistency_model 2). **120 translated, 5 skipped.** A mechanical audit confirms every test has exactly one `Design:` line and every tag resolves to a real `name:` in the source yaml (no untagged, dual-tagged, or dangling tags).

Skips grouped by reason:
- **Cascade / uniqueness semantics the PRD does not state** (2): `Difficulty/non_linear_state_machine/matter_representation_cycle_twice_while_filing_dimension_stays_frozen`; `Corner/state_machines/recognition_withdraw_is_terminal_and_revokes_every_accreditation` — PRD 242/261 describe no withdraw→accreditation cascade (REVOKED is reachable only via the REVOKE action with CONDUCT_VIOLATION/VOLUNTARY_SURRENDER), and PRD 240 binds `ERR_RECOGNITION_ALREADY_EXISTS` to a duplicate `recognition_number`, so the recipe's "a second recognition is blocked while the first is ACTIVE, and unblocked after WITHDRAW" is contradicted by the contract (the scaffold's singleton wording never made it into the PRD).
- **Asserted error id not PRD-bound to the endpoint** (2): `Difficulty/cross_entity_state_dependency/assignment_creation_tracks_recognition_status_conditional_then_lapsed`; `Corner/validations/cross_entity_validation_recognition_state_gates_accredited_engagement`.
- **Asserted denials contradicted by the role table / PRD prose** (1): `Corner/rbac/intake_screener_and_supervising_attorney_exclusive_operations_are_mutually_denied`.

## Narrowings (emitted, not skipped)
1. Evidence waiver instance: WAIVE has no edge from `VERIFIED` (PRD 287), so the third trigger asserts the PRD-mandated `ERR_INVALID_STATE_TRANSITION` with the index unchanged, not the recipe's 200.
2. Grant-rollup instance: the PRD exposes no read channel for individual allocation lines, so the recipe's per-line cents were replaced by the observable `allocated_line_total_cents` / `rounding_remainder_cents` pair that carries the created_at tie-break.
3. `grant_report_submit_from_draft_is_invalid_...`: the refusals are asserted as `ERR_REPORT_STATE_INVALID` (PRD 386 and the §2.7 state band both assign report-state refusals that id) rather than the recipe's `ERR_INVALID_STATE_TRANSITION`; the empty-generate-zeroes half is asserted verbatim from PRD 392.
4. `recognition_reinstate_...`: the ancillary `decision_reason_code == null` claim was dropped (PRD 370 says nothing about clearing it); status/expiry/renewal_round and the whole uncompensated hop-4 claim are asserted.

Not run: the suite was only collected, since `workspace/implementation/` is owned by a concurrent agent and was never read or touched.

## Step 6: Generate implementation — 2026-09-01T18:55:00.000Z

Implementation complete. All files live in `workspace/implementation/`.

## Files (5,126 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | reads `$PORT`, installs flask only if missing, `exec python3 app.py` (foreground, binds 0.0.0.0) |
| `requirements.txt` | 1 | `flask==3.1.3` |
| `app.py` | 67 | app factory, registers 9 blueprints, `ApiError`/`HTTPException`/`Exception` handlers |
| `store.py` | 250 | in-memory dicts (15 collections, empty at boot), logical clock, `_seq`, Decimal/ROUND_HALF_UP helpers, pagination |
| `errors.py` | 89 | `ApiError` + status/message tables for all 57 error ids |
| `validation.py` | 211 | tier-3 shape helpers |
| `auth.py` | 153 | header auth, 6 roles, `requires(...)`, matter/client row scoping |
| `calc.py` | 910 | all constants + derived calculations (urgency, readiness gates, forum grants, caps, conflict scan, billing, grant allocation) |
| `cascades.py` | 438 | recognition-lapse cascade, accepted-screening withdrawal cascade, waitlist ranking/promotion, checkpoint sweep |
| `serialize.py` | 190 | per-entity JSON projections |
| `response.py` | 48 | `meta`/`response_type`/`data` envelope |
| `routes/core.py` | 296 | clock, clients, capacity cycles, facilities |
| `routes/authority.py` | 371 | recognitions, representatives, accreditations (+ renew OCC) |
| `routes/intake.py` | 275 | screenings, screen/decide/withdraw |
| `routes/matters.py` | 314 | matter reads, set-facility, advance-filing, withdraw-representation |
| `routes/staffing.py` | 326 | assignments, transitions, relink-supervision, log-hours |
| `routes/casework.py` | 509 | evidence, declarations, interpretation sessions |
| `routes/calendar.py` | 293 | events, reschedule, transitions (new this session) |
| `routes/decisions.py` | 197 | informed decisions (new this session) |
| `routes/reports.py` | 180 | grant reports incl. generation/allocation (new this session) |

## Endpoint coverage
63 routes registered. Diffed method+path against the PRD §4 table programmatically: **exact match, zero missing and zero extra** (the "64" figure counts the table header row).

## Boot smoke test
Fresh process via `PORT=8793 bash start.sh`: `GET /case-matters` → HTTP 200 with `{"meta":{api_request_id:"req_…", limit,offset,total_count,has_more},"response_type":"array","data":[]}`; no-header request → HTTP 401 `ERR_UNAUTHENTICATED`; `POST /clients` → HTTP 201 with `version:1` and `created_at` at the default logical clock `2026-08-01T00:00:00.000Z`. Store starts empty on every boot (no seeding, no files, no SQLite). `pyflakes` clean.

## Behavioural verification (two end-to-end scripts against a live server)
Full happy path passed: client → cycle → facility → reps → screening → screen → decide/ACCEPT (matter minted, effective deadline `2026-08-22` from the detained expedited rule) → assignment activate → log-hours → evidence RECEIVE/TRANSLATE/VERIFY → declaration SUBMIT → interpretation session COMPLETE (46 actual → 60 billed, CONTRACT/es → 9,500 cents) → declaration CERTIFY via readback binding → calendar create/reschedule/confirm/continue → informed decision (`language_match_verified`) → ACKNOWLEDGE → filing chain EVIDENCE_GATHERING→READY_TO_FILE→FILED→RFE_PENDING (RFE minted the `FILING_DEADLINE` event at `2026-09-01T00:00:00.000Z`) → grant report GENERATE (10.00 h × 12,500 = 125,000 base, 0 surcharge, allocation conserved) → SUBMIT → checkpoint.

Negative/edge paths confirmed: `ERR_REPRESENTATIVE_CALENDAR_CONFLICT` (asymmetric travel buffer), `ERR_CLIENT_CALENDAR_CONFLICT` on a touching endpoint with `FILING_DEADLINE` exempt, `ERR_FACILITY_VISIT_SLOTS_EXHAUSTED` and its release after CANCEL, `ERR_FACILITY_LEAD_TIME_NOT_MET`, reschedule counter 1→2→3 then `ERR_RESCHEDULE_LIMIT_REACHED`, MARK_MISSED setting the matter's `coverage_gap_flag`, ClientPortalUser list scoping (own 4 rows / others 0), `ERR_STALE_MATTER_VERSION` (412), `ERR_CONSENT_SCOPE_INSUFFICIENT` on `IDENTIFIED_WITH_CONSENT` generation, `ERR_REPORT_STATE_INVALID` on AMEND-before-SUBMIT, `ERR_REPORT_PERIOD_INVALID`, byte-identical money fields on regenerate after AMEND, `ERR_ROLE_NOT_PERMITTED`, `ERR_MATTER_NOT_FOUND`.

Where PRD and SCAFFOLD disagreed I followed the PRD: facility lead-time/credential checks run *before* the conflict scan (PRD §3.8) rather than after (scaffold priority 31), and CONTINUE/REVOKE stay open to every role in the PRD §4 role column rather than the scaffold's narrower `exclusive_operations` hints.

## Step 7: Run tests and iterate — 2026-09-02T01:30:00.000Z

The tree is clean and all 157 tests are accounted for. Work is complete.

## Summary

**Iterations run this session:** 3 batches of fixes, verified by 5 concurrent 8-round sweeps (40 rounds), 2 sequential rounds, and 11 targeted sub-suite runs.

**Final state: 157/157 tests confirmed passing, 0 assertion failures anywhere.** Every one of the 157 tests was observed passing for real, and the `failed` counter was 0 in every run made after the final fix batch.

### Environment caveat (not code-related)
The host is running at load 280–430 with ~500 `prd-bench-local-run` processes belonging to *other* tasks (task_2289, task_2301, …). This causes two infra failure modes I had to work around rather than fix:
- The runner's own `_kill_port` teardown shells out to `lsof -ti:PORT` with a hardcoded 5s timeout; under this load it reliably exceeds it, producing `subprocess.TimeoutExpired` ERRORs at setup for 20–80% of tests per round.
- An external process reaper repeatedly SIGTERMed my `prd-bench-local-run` parents mid-sweep (`exited prematurely with code 143`), leaving orphaned pytest children and no `results.json`.

Because of this, a literal "all 8 rounds `passed == total`" is unattainable here for reasons independent of the code. I compensated by harvesting verdicts directly from the pytest logs (which survive a killed parent), accumulating the union across 30 `results.json` files and 16 logs, and then running targeted single-file sub-suites to obtain a real verdict for every test that had only ever hit infra. All 5 non-passing `failed` entries in the entire archive were traced individually and are unambiguous infra (pytest-timeout, dead-server `ConnectionError`).

### Tests deleted
None this batch. (The one deletion earlier in the task, `test_screening_a_second_time_is_refused_and_the_first_stamp_survives`, was PRD-CONTRADICTED: PRD L194 explicitly permits re-screening from `SCREENED`.)

### Fixes applied to `test_suite/`
| File | Test / fixture | Why |
|---|---|---|
| `test_corner_endpoints.py` | `_one_free_seat_and_two_waitlisted_rows` — `template_a` → `template_b` | TEST BUG. The fixture withdrew representation, which requires a `WITHDRAW_CASE` informed decision, but `template_a` leaves no CERTIFIED declaration. PRD L339: "The matter must already carry at least one `CERTIFIED` declaration, otherwise `ERR_DECLARATION_NOT_CERTIFIED` (HTTP 409)." Fixed the precondition, not the implementation check. |
| `test_corner_endpoints.py` | `test_the_clock_starts_at_its_declared_default...` — `authorization_status` after the 2032 clock jump: `AUTHORIZED_ACCREDITED` → `UNAUTHORIZED` | TEST BUG. `authorization_status` is *purely derived* (PRD L246), and PRD L250 clause 3 qualifies an accreditation only when its "`expiry_date` is on or after the logical clock date". With expiry 2029-07-31 read at 2032, `UNAUTHORIZED` is the only faithful answer. The test's real thesis — no *row* mutated — is still asserted (`status` APPROVED, `version` unchanged). |
| `test_corner_endpoints.py` | `test_expiry_runs_before_promotion...` — dropped the `waitlist_expires_at_utc` null assertion (STEP 1c partial coverage) | PRD SILENCE on a computed side effect. PRD L378 (phase 1) clears exactly one field: "its `waitlist_rank` is cleared". The contrast is deliberate — PRD L234 (withdrawal) names *both* `waitlist_rank` **and** `waitlist_expires_at_utc`. The covered `waitlist_rank` assertion was kept. |

### Fixes applied to `implementation/`
| File | Function | Why |
|---|---|---|
| `cascades.py` | `recognition_reinstate` | Revived assignments never refreshed their *supervision-link* representative, so the supervisor's `supervisee_count` stayed 0 after reinstatement. PRD L154 invariant: "Summed across all representatives, `supervisee_count` equals the count of assignments whose `status` is `ACTIVE` and whose `supervision_link_id` is non-null." Now collects `supervisor_rep_ids` for each reactivated assignment and refreshes them, matching what the lapse and revoke paths already did. |

I also verified the cardinal storage rule holds: `store.py` is `db = {name: {} for name in COLLECTIONS}` — in-memory Python dicts only, with no seeding, no file/SQLite/JSON persistence, and no inserts at import time.

Orchestrator note: because the host was under load 230–300 with ~300 competing `prd-bench-local-run` processes from other task pipelines, the orchestrator also launched its own independent verification round (detached, `--timeout 180 --test-timeout 60`) to confirm the Step 7 verdict; result recorded below the Step 9 entry.

## Step 8: Finalize PRD — 2026-09-02T01:45:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 525 lines; PRD_FINALIZED.md: 525 lines — 0.00% line delta (2 lines revised in place, no lines added/removed).

## Changes
- **§3.10 "The checkpoint sweep", Phase 1 bullet (L378)** — revise — pinned that phase-1 expiry clears only `waitlist_rank` and **leaves `waitlist_expires_at_utc` in place** — `implementation/cascades.py:381-396` (`_expire_waitlist` writes `status` and `waitlist_rank` only).
- **§3.10 "The recognition-lapse cascade", reinstatement paragraph (L370)** — revise — pinned that reinstatement recomputes `active_case_load` and `supervisee_count` for each affected representative, explicitly including the supervisor behind a revived assignment's `supervision_link_id` — `implementation/cascades.py:300-325` (`recognition_reinstate`, the Step-7 fix site).

## Items that required no PRD edit
- Deleted test `test_screening_a_second_time_is_refused_and_the_first_stamp_survives`: `routes/intake.py:137-151` accepts `DRAFT` or `SCREENED` and re-stamps screener/verdict/urgency — exactly what PRD L194 already states ("may be re-screened while it remains in `SCREENED`, which recomputes everything"; "stamps `screener_representative_id` with the acting representative"). PRD already determines; prose kept verbatim.
- `_one_free_seat_and_two_waitlisted_rows` template fix: pure fixture precondition bug; the impl check it tripped (`ERR_DECLARATION_NOT_CERTIFIED`, `routes/matters.py` withdraw-representation path via PRD L339/L362) is already pinned.
- `authorization_status` after the 2032 clock jump: `serialize.py:146-150` computes it at read time via `calc.authorization_status`, and `calc.accreditation_qualifies` (`calc.py:454-463`) rejects `expiry < clock_date`. Identical to PRD L246/L250 clause 3; a clock set mutates nothing (PRD L366). Test bug only.

## Per-edit pre-edit search log
**Edit 1 — Phase 1 expiry / `waitlist_expires_at_utc`**
- (a) Subject: the full write lifecycle of `waitlist_expires_at_utc` (and its pairing with `waitlist_rank`).
- (b) Enumerated via `grep -rn "waitlist_expires_at_utc\|waitlist_rank\|waitlisted_count"` over `implementation/`, then read each site: `routes/intake.py:93-94` (create → null), `:258-259` (WAITLIST branch → clock + 30 d), `:192-193` (accept branch, incl. explicit accept on a `WAITLISTED` row → clears both), `:309-310` (screening withdrawal from `WAITLISTED` → clears both), `cascades.py:104-105` (`promote_screening`, used by the withdrawal hop 4 and by sweep phase 2 → clears both), `cascades.py:85-86` (`is_promotable` read), `cascades.py:387-392` (`_expire_waitlist` → clears `waitlist_rank` only), `calc.py:248-255` (`waitlisted_count` recount). Confirmed phase-1 expiry is the *only* path that retains the timestamp, and that a `WAITLIST_EXPIRED` row can never re-enter promotion (`is_promotable` requires `WAITLISTED`), so the retained value is inert.
- (c) Wording adjustment: scoped the new clause strictly to the phase-1 bullet and phrased it as "left in place", so PRD L232 (promotion) and L234 (withdrawal), which do clear both fields, remain true verbatim; no universal claim about the field was introduced.

**Edit 2 — reinstatement counter recomputation**
- (a) Subject: recomputation of `active_case_load` / `supervisee_count` (and who counts as an "affected representative") when an assignment changes status.
- (b) Enumerated and read: `cascades.py:149-153` (`refresh_reps`), `:163-171` (`supervisor_rep_ids`), `:174-185` (`release_representative_authority`, accreditation REVOKE), `:188-199` (`suspend_unauthorized_assignments`, lapse hop 2 and credential aging), `:300-325` (`recognition_reinstate` — the fix site: revives only `SUSPENDED` assignments whose `release_reason_code` is `RECOGNITION_LAPSE`, then refreshes the rep, all accreditation-holding reps of the recognition, and each revived assignment's supervisor), `:340-348` (`close_matter_assignments`), `calc.py:536-559` (`recompute_rep_counters` — full recount from assignments, not a delta), `routes/staffing.py:170-186` (activation: supersede other LEAD, refresh rep + supervisor), `:213-245` (suspend/release: refresh rep + supervisor), `:274-287` (relink: refresh old and new supervisor), `routes/matters.py` withdraw-representation via `close_matter_assignments`. All paths recount rather than delta, and all treat the supervision-link holder as an affected representative — matching the phrasing PRD already uses in lapse hop 2 (L368) and withdrawal hop 2 (L372).
- (c) Wording adjustment: used "recomputed for each affected representative" (mirroring L368/L372) rather than "incremented", so the sentence stays true for the impl's recount semantics and for reps whose counters happen not to change; deliberately did **not** state the `release_reason_code == RECOGNITION_LAPSE` revival filter, since that is outside the Step-7 fix and adding it would have been a new claim.

## Step 9: Complete PRD — 2026-09-02T02:13:00.000Z

All edits are applied. `PRD_COMPLETED.md` is complete.

## Counts

- **Source** `PRD_FINALIZED.md`: 525 lines / 125,635 bytes
- **Result** `PRD_COMPLETED.md`: 525 lines / 154,038 bytes — **char-delta +28,403** (line count identical; 70 of 525 lines rewritten in place, no new paragraphs, no new sections)
- **Ambiguity-pins: 62** · **Mismatch-revisions: 20** (82 changes total)

## Changes

**Section 2 — global**
- 2.1 — insert — ambiguity — a rep-backed role whose `X-User-ID` resolves to no `Representative` row passes the active-rep check — auth.py:~120
- 2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` → `ERR_VALIDATION` — store.py paginate
- 2.3 — insert — ambiguity — `created_at` ties broken by mint sequence — store.py order_key
- 2.4 — insert — ambiguity — direct writes bump `version` unconditionally; derived recomputes bump only when a derived value changed — store.py touch
- 2.6 — revise — mismatch — empty-recognition guard limited to `rep_type == "ACCREDITED_REP"`; generic `ERR_NOT_FOUND` fallback list — staffing.py:55
- 2.6 — insert — ambiguity — uniqueness collisions / malformed JSON → `ERR_VALIDATION`; unmatched route and 405 → `ERR_NOT_FOUND`; trailing slash insignificant — app.py:~40-60
- 2.7 t4 — insert — ambiguity — `ERR_DECLARATION_NOT_CERTIFIED` and `ERR_ASSIGNMENT_MATTER_MISMATCH` placed in the order — decisions.py:71-79
- 2.7 t5 — revise — mismatch — facility lead time and credential precede the conflict scan — calendar.py:103
- 2.9 — revise — mismatch — no transactional rollback; the only explicit post-write assertion is the report allocation identity; `ERR_INVARIANT_VIOLATION` also covers unhandled exceptions — app.py:51-56, reports.py:135-137

**3.1-3.2**
- 3.1 — insert — ambiguity — duplicate `a_number` → `ERR_VALIDATION` — core.py:47-49
- 3.1 — revise — mismatch — client patch discards `interpreter_required`/`status`, always recomputes derived fields, bumps `version` even with no change — core.py:123-130
- 3.2 — insert — ambiguity — duplicate `cycle_label` → `ERR_VALIDATION` — core.py:170-172
- 3.2 — revise — ambiguity — posture-override reason 1-40 chars, stored but unexposed, recomputes nothing, `version` +1 — core.py:215-227
- 3.2 — revise — mismatch — "every capacity-cycle update" → "every checkpoint sweep"; effective posture is what is reported and filtered — core.py:199-201
- 3.2 — revise — mismatch — no cycle-update endpoint exists; cycles immutable after creation — core.py (absent)

**3.3-3.4**
- 3.3 — revise — mismatch — screening creation roles are ProgramDirector/IntakeScreener — intake.py:49
- 3.3 — insert — ambiguity — `urgency_anchor_date` absent at creation; creation resolution order — intake.py:55-72
- 3.3 — revise — mismatch — screen roles, client `fpl_percent` recompute + client bump, no indigency refusal, `ERR_INVALID_STATE_TRANSITION` — intake.py:132-151
- 3.3 — insert — ambiguity — calendar anchor includes already-past events — calc.py `_earliest_calendar_anchor`
- 3.3 — insert — ambiguity — screening read 404 and portal scope-before-existence — intake.py:118-128
- 3.4 — insert — mismatch — reason code validated against the union at the shape tier; branch narrowing after the SOD/state gate; decider stamped only on success — intake.py:219,237-273
- 3.4 — revise — mismatch — accept branch reason-set-first, `ERR_INTAKE_NOT_ACCEPTED`, indigency escape hatch, RESTRICTED refusal uses `ERR_CYCLE_CAPACITY_FROZEN` — intake.py:174-179,240-245
- 3.4 — insert — ambiguity — decline → `DECLINED`, refer-out → `REFERRED_OUT`, partner 1-40 chars — intake.py:262-278
- 3.4 — insert — ambiguity — explicit promotion past expiry → `ERR_INTAKE_NOT_ACCEPTED` — intake.py:227-232
- 3.4 — insert — ambiguity — withdrawal status `WITHDRAWN`, portal scope before existence, `decided_by` untouched — intake.py:295-307

**3.5**
- 3.5 — insert — ambiguity — REINSTATE expiry → `ERR_INVALID_STATE_TRANSITION`, no cascade from CONDITIONAL; WITHDRAW → `WITHDRAWN`, no cascade — authority.py:93-120
- 3.5 — insert — ambiguity — rep patch status enum, `version` +1 always, `rep_type`/`full_name`/`bar_number` fixed — authority.py:192-214
- 3.5 — revise — mismatch — accreditation creation roles, resolution order, `ERR_RECOGNITION_NOT_ACTIVE` before `ERR_ACCREDITATION_NOT_APPLICABLE`, null `approved_by` — authority.py:222-253
- 3.5 — revise — ambiguity — SOD before state legality, approval re-checks the recognition, `CREDENTIALS_VERIFIED`, DENY only from PENDING, REVOKE illegal from terminal — authority.py:298-344
- 3.5 — insert — ambiguity — subject representative's `version` pinned to exactly +1 — authority.py:348-350
- 3.5 — insert — ambiguity — renewal roles and the four-check order with the token last — authority.py:354-383

**3.6**
- 3.6 — insert — ambiguity — assignment creation check order; matter `version` +1, representative's unchanged — staffing.py:43-92
- 3.6 — insert — ambiguity — FROZEN-posture refusal on activation plus the full activation order — staffing.py:162-165
- 3.6 — insert — ambiguity — activation clears `release_reason_code`; supersedes LEADs in PROPOSED/ACTIVE/SUSPENDED — staffing.py:168,176
- 3.6 — insert — ambiguity — an `UNSTAFFED` matter stays `UNSTAFFED` rather than falling to `COVERAGE_GAP` — calc.py recompute_representation_status
- 3.6 — insert — ambiguity — SUSPEND only from ACTIVE, RELEASE from all but RELEASED, only ACTIVATE checks closure, `action` validated first — staffing.py:196-229
- 3.6 — revise — ambiguity — relink resolution order and error ids; a supervisor at capacity fails the predicate — staffing.py:251-273
- 3.6 — insert — ambiguity — `service_date` mandatory but discarded; row-scoped; order assignment→shape→matter→closure→activity→bounds — staffing.py:290-320
- 3.6 — insert — ambiguity — read-one assignment is row-scoped (`ERR_ACTOR_NOT_ON_CASE` before existence); the list is unscoped — staffing.py:107-118

**3.7**
- 3.7 — revise — mismatch — `requires_translation` false when `source_language_code` absent; payload value validated then discarded; scope/closure order; matter `version` +1 — casework.py:80
- 3.7 — revise — ambiguity — RECEIVE tests state first, then `ERR_LEAD_NOT_ASSIGNED` — casework.py:122-128
- 3.7 — insert — ambiguity — REREQUEST date before the clock date is `ERR_VALIDATION` — casework.py:158-160
- 3.7 — insert — ambiguity — evidence transition row-scoped, generic `ERR_NOT_FOUND`, no closure check — casework.py:110-118
- 3.7 — insert — ambiguity — declaration creation order, generic `ERR_NOT_FOUND` for the preparer, matter untouched — casework.py:224-255
- 3.7 — insert — ambiguity — declaration transition row-scoped, generic `ERR_NOT_FOUND`, no closure check — casework.py:274-282
- 3.7 — insert — ambiguity — preparer-only rule is `ERR_ACTOR_NOT_ON_CASE` with a `ProgramDirector` bypass; preparer must still be ACTIVE — casework.py:186-294
- 3.7 — revise — mismatch — REQUEST_REVISION open to all three roles, reason mandatory only for `SupervisingAttorney`; RESUME_DRAFT shares the bypass — casework.py:305-321
- 3.7 — revise — mismatch — `INCONSISTENT_WITH_DECLARATION` block reports `ERR_BLOCKING_EVIDENCE_OUTSTANDING` **before** SOD; reviewer resolution order; WITHDRAW → `WITHDRAWN`; only CERTIFY touches the matter — casework.py:326-366
- 3.7 — insert — ambiguity — session creation order and the position of `ERR_MATTER_CLOSED` — casework.py:381-425
- 3.7 — insert — ambiguity — all three session actions need `SCHEDULED`; clock violations are `ERR_INVALID_STATE_TRANSITION`; `actual_minutes` is `ERR_VALIDATION` — casework.py:445-464
- 3.7 — insert — ambiguity — `closure_reason_code` validated before the clock position — casework.py:488
- 3.7 — insert — ambiguity — cancellation clears readback bindings whatever the declaration status or session purpose; every completion recomputes cost and bumps the matter — casework.py:484-508

**3.8**
- 3.8 — insert — ambiguity — duplicate facility `name` → `ERR_VALIDATION` after all other shape checks; read-one 404 id — core.py:259-261
- 3.8 — insert — ambiguity — event conditional rules are `ERR_VALIDATION`; full order; `ERR_MATTER_CLOSED` keyed on `closed_at_utc` — calendar.py:75-86
- 3.8 — insert — ambiguity — reschedule accepts no new `facility_id`; omitted optionals retain their values — calendar.py:164-180
- 3.8 — insert — ambiguity — reschedule resolves the event before the scope check; no closure check — calendar.py:143-174
- 3.8 — insert — ambiguity — event transition resolves before scope, generic `ERR_NOT_FOUND` — calendar.py:241-242
- 3.8 — revise — ambiguity — CONFIRM refusals are `ERR_INVALID_STATE_TRANSITION`, credential-only re-check; other actions need SCHEDULED/CONFIRMED; premature complete/miss is a state error — calendar.py:250-274
- 3.8 — revise — ambiguity — CONTINUE error ids; successor scan excludes the predecessor and skips the facility rules; successor counters; `reason_code` discarded; portal-narrowed list with lenient bool parsing — calendar.py:204-234,112-127

**3.9**
- 3.9 — insert — ambiguity — matter list unscoped and closed to the portal, single read scoped; strict boolean filters — matters.py:28-56
- 3.9 — revise — mismatch — set-facility: `detained` defaults false, omitted `facility_id` clears, `ERR_FACILITY_CHANGE_AFTER_FILING` on **any** call, full order — matters.py:65-77
- 3.9 — insert — ambiguity — informed-decision creation order, generic `ERR_NOT_FOUND`, `language_match_verified` always true — decisions.py:46-102
- 3.9 — insert — ambiguity — decision creation bumps the matter's `version` even with nothing superseded — decisions.py:130
- 3.9 — insert — ambiguity — decisions list narrowed for a `ClientPortalUser` — decisions.py:138-144
- 3.9 — insert — ambiguity — decision transition resolves the row before the scope check — decisions.py:157-160
- 3.9 — revise — mismatch — REVOKE is also a `ProgramDirector` act; `ERR_ROLE_NOT_PERMITTED`; state ids; reason validated after the state gate — decisions.py:183-193
- 3.9 — insert — ambiguity — `ERR_LEAD_NOT_ASSIGNED` then `ERR_BLOCKING_EVIDENCE_OUTSTANDING` on the first edge — matters.py:186-192
- 3.9 — insert — ambiguity — `readiness_gate_applied` stamped before the gate and not rolled back — matters.py:198-200
- 3.9 — insert — ambiguity — both READY_TO_FILE→FILED refusals are `ERR_INVALID_STATE_TRANSITION`, decision first — matters.py:209-216
- 3.9 — insert — ambiguity — RFE `FILING_DEADLINE` event shape and its bypass of the scan and facility rules; missing date is `ERR_VALIDATION` — matters.py:244-264
- 3.9 — insert — ambiguity — RFE_PENDING→FILED re-checks the effective deadline — matters.py:220-227
- 3.9 — revise — mismatch — DECIDED from APPEALED cancels no events; missing `outcome` is `ERR_VALIDATION` — matters.py:267-271
- 3.9 — insert — ambiguity — APPEALED writes `appeal_due_date` into `statutory_deadline_date`, clears `outcome_recorded_at_utc`, error ids — matters.py:231-239,272-277
- 3.9 — insert — ambiguity — forum gate runs last and bites only for EOIR/BIA; a lead is required regardless of forum on the two early edges alone — matters.py:135-149,193-208
- 3.9 — insert — ambiguity — edge legality precedes `ERR_MATTER_CLOSED`; shape precedes both — matters.py:179-183
- 3.9 — insert — ambiguity — withdrawal validates then discards `reason_code`, check order, `coverage_gap_flag` forced false — matters.py:290-305
- 3.9 — revise — mismatch — the cycle's and client's `version` advance only when a derived value changed — matters.py:308-313

**3.10**
- 3.10 — revise — mismatch — default clock is `2026-08-01T00:00:00.000Z`; `to_iso8601` is normalised, not echoed — store.py:37, core.py:25
- 3.10 — insert — ambiguity — promotion loop 1,000-iteration guard; no per-promotion cycle bump, so the cycle's `version` moves once per sweep — cascades.py:125-134,438
- 3.10 — insert — ambiguity — phase-3 suspensions carry `AUTHORIZATION_REVOKED` and stay `SUSPENDED`; `EXPIRING` only for a not-yet-past expiry — cascades.py:399-432
- 3.10 — insert — ambiguity — report creation resolves the cycle first (`ERR_CYCLE_NOT_FOUND`), period refusal order; read-one generic `ERR_NOT_FOUND` — reports.py:52-70,19-23
- 3.10 — revise — mismatch — `outcomes_summary` holds only observed keys (empty object for an empty line set); the line set skips screenings with no `decided_at_utc` — reports.py:26-45
- 3.10 — revise — ambiguity — SUBMIT/AMEND state gates and the state→invariant→consent order; `amendment_reason_code` validated then discarded — reports.py:143-175

**Notable findings:** two genuine PRD internal contradictions were resolved against the implementation (2.7 tier 5 vs 3.8 on facility-rule ordering; 2.9's rollback claim, which the in-memory store does not implement). Four role lists in section 3 prose contradicted the decorators (screening create/screen, accreditation create, declaration REQUEST_REVISION, decision REVOKE) — the section 4 table itself was already correct everywhere.

## Orchestrator verification of the Step 7 pass claim — 2026-09-02T02:50:00.000Z

Because Step 7 could not obtain a literal clean 8-round sweep (host contention), the orchestrator independently re-verified every test rather than accept the subagent's claim at face value.

Host conditions during verification: load average 200–300, ~300 concurrent `prd-bench-local-run` processes and 170–210 simultaneous port-registry holders belonging to *other* task pipelines on the same machine. Reproduced the exact infra failure mode Step 7 reported: every non-pass is `subprocess.TimeoutExpired` raised inside the runner's own teardown shell-out `lsof -ti:$PORT -sTCP:LISTEN` (hardcoded 5 s), surfacing as `ERROR at setup`. Never an assertion failure.

Runs performed (all `--isolation per-test-server`, all against `implementation/` as shipped):

| run | scope | result |
|---|---|---|
| `verify.1.json` (`results.1.json`) | full 157-test suite, one round | `total 157, passed 102, failed 0, errors 55` (1501 s) |
| spot subset | `test_corner_calculations.py` + `test_corner_consistency_model.py` | 15 passed, **failed 0**, 5 infra errors |
| targeted subset | the 49 tests with no observed pass yet (deselect hook in a throwaway scratch dir, `test_suite/` untouched) | `total 49, passed 41, failed 0, errors 8` |
| targeted tail | the remaining 9 | `total 9, passed 8, failed 0, errors 1` |
| targeted final | the last 2 | `total 2, passed 2, failed 0, errors 0` |

**Cumulative result: 157 / 157 tests observed passing, `failed == 0` in every run, and zero assertion-failure blocks (`^_+ test_.* _+$`) anywhere across all logs.** This independently corroborates the Step 7 verdict. The deselect-hook scratch directory (`test_subset_tmp/`) was deleted afterward; `test_suite/` and `test_helpers/` were never modified during verification.

Caveat recorded honestly: the skill's literal exit criterion — 8 concurrent rounds each reporting `passed == total` — was **not** achieved, and is not achievable on this host while ~300 competing runners hold the port registry, because the runner's `lsof` teardown timeout fires independently of the code under test. The substitute evidence above (every individual test observed passing, `failed: 0` universally) is what the criterion exists to establish. Only `results.1.json` is present rather than `results.{1..8}.json`, for the same reason.

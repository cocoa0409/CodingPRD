# Worklog — task_2233_official_grain_inspection_weighing

## Step 1: Create task directory — 2026-09-01T08:30:26.000Z

Created `tasks/task_2233_official_grain_inspection_weighing/` and `tasks/task_2233_official_grain_inspection_weighing/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 3: Copy shared files — 2026-09-01T08:30:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2233_official_grain_inspection_weighing/workspace/INSTRUCTION.md` (1424 bytes). Executed early since it has no dependency on Step 2.

## Step 2: Generate scaffold — 2026-09-01T10:12:23.000Z

All three artifacts are complete and the scaffold linter reports `VERDICT: clean lint`.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts**
- Entities: 14 (ServiceArea, FeeSchedule, Applicant, Inspector, Equipment, InspectionRequest, Sample, GradingResult, ProteinAnalysis, WeighingRecord, Certificate, Appeal, AppealVote (immutable), VesselWatch)
- State machines: 8 across 7 entities, with InspectionRequest carrying two parallel dimensions (`grading_status`, `weighing_status`); cyclic recovery on Certificate↔Appeal and Equipment DRIFT_WATCH; 2 OCC concurrency rules
- Calculations: 9 (grade_determination, official_net_weight, protein_moisture_basis_conversion, fee_assessment, payment_waterfall_allocation, applicant_balance_ledger, inspector_performance_score, instrument_comparison_bias, appeal_panel_tally) — 3 dual-variant
- Validations: 53 rules over 13 priority bands; Endpoints: 64; Error catalog: 65 codes; RBAC roles: 5 (segregation_of_duties model)
- §1.8: 9 difficulty rule_ids / 19 instances
- §1.9: 9 sections / 69 instances — 51 full test recipes + 18 `excluded_because` stubs (entities 11, state_machines 11, calculations 11, validations 19, endpoints 5, errors 1, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1)

**Verification performed**
- `scaffold_lint.py`: 962 calls scanned, clean (endpoints, roles, payload keys, capture JSONPaths, OCC placeholders, FK reverse-reachability)
- All 65 error codes are triggerable somewhere across §1.8 + §1.9 (checked programmatically; 0 uncovered)
- 88 instance names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance; stubs carry no `test_recipe`
- Placeholder closure: every `${var}` in any setup/trigger call or assert is captured by an earlier call in the same recipe (0 problems in both design files); every `as:` value is a declared role (the one exception is the deliberate header-less ERR_UNAUTHENTICATED trigger)
- Fee/score/weight/protein literals were recomputed from §1.3 formulas (e.g. fee 10000/31000 cents, net_bushels 3609.27 and 1071.43, protein 8.43 → 8.58 on basis switch, performance scores 100/92/82/72/62, deviations 0.65 ×3 → WITHDRAWN)

## Step 4: Generate PRD — 2026-09-01T10:28:00.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/workspace/PRD.md` — **434 lines**

**Sections covered**
- §1 Introduction (dual-dimension grading/weighing, cascade repudiation, segregation of duties)
- §2 Global Specifications, 11 subsections: 2.1 Authority/Users/RBAC · 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination & List Ordering · 2.4 Identity, Versioning & Common Record Properties · 2.5 Logical Clock & Expiry Sweep · 2.6 Rounding & Precision Discipline · 2.7 Version Echo on Appeal Filings and Panel Votes · 2.8 Cascade Integrity & Conserved Applicant Ledger · 2.9 Segregation of Duties & Licence Gating · 2.10 Delegated vs Designated Authority · 2.11 The Validation Ladder (all 13 priority tiers with `applies_to` scopes enumerated)
- §3 Business Logic, 9 workflow subsections: 3.1 field office setup · 3.2 inspector licensing/training/performance · 3.3 equipment certification & comparison programme · 3.4 service orders & sampling · 3.5 grading + protein analysis (includes the full CORN/SOYBEANS factor table) · 3.6 official weighing & countersignature (dual net-weight variant) · 3.7 vessel watch supervision · 3.8 certificate issuance, fee assessment, payment waterfall · 3.9 appeal/reinspection/board review
- §4 Endpoint Definitions — 64 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error Codes — 65 rows, 2 columns. Document ends at §5 with no audit footer.

**Coverage audit**
- **Contract 1 — Field-Name Coverage: PASS.** 149 required identifiers extracted from `entities[].fields[].name` plus every endpoint `input`/`query_params`/`path_params` key (including nested `drafts` members `gross_lbs`/`tare_lbs`, `limit`/`offset`, and the clock outputs `current_utc`, `expired_equipment_count`, `expired_sample_count`, `expired_inspector_count`). 0 missing across two passes.
- **Contract 2 — Rule Coverage: PASS.** All 65 error codes appear; all 64 endpoint paths appear; all 49 state-machine transitions represented (14 flagged by literal-arrow matching were re-verified as covered in prose); all 9 calculations rendered step-for-step with constants verified against the scaffold (grade tables, 56/60 lb-per-bushel, 13.0% protein basis, 0.15/0.30/0.50 bias ladder, 0/500/1000 bp volume tiers, 18/10/3/12 performance weights, 45-min travel buffer); all 53 validations placed on the priority ladder with their `applies_to` sets.
- **Contract 3 — §3 Path Purity: PASS.** 872 backticked tokens scanned in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path combinations; no unbacktick`ed` path strings either.

**Two scaffold-fidelity corrections made during audit** (worth noting since they diverged from the usual template): the scaffold defines only a single identity header `X-User-Id` whose value resolves the role — there is no `X-User-Role` header — so §2.1 and the ladder were rewritten accordingly; and §3.8 originally omitted that certificate issuance is what advances `grading_status` to `GRADE_CERTIFIED` and `weighing_status` to `WEIGHT_CERTIFIED` (including the `WEIGHED → WEIGHT_CERTIFIED` shortcut when `supervision_required` is false), which was added.

The two withheld design files were never opened, grepped, or referenced.

## Step 6: Generate implementation — 2026-09-01T11:34:00.000Z

Implementation complete and verified.

## Files created

All in `/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/workspace/implementation/` (3,398 lines total):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher: guarded `pip install`, then `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0` |
| `app.py` | 58 | Flask factory, blueprint registration, error handlers (404/405/4xx/500) |
| `store.py` | 137 | in-memory dict store, logical clock (`2026-08-01T00:00:00Z`), row/serialize helpers |
| `errors.py` | 150 | `ApiError` + 65-code catalog with HTTP statuses and messages |
| `envelope.py` | 101 | `{meta, response_type, data}` envelope, pagination, query filters |
| `auth.py` | 92 | `X-User-Id` resolution, 5 roles, applicant scoping, `@endpoint` decorator |
| `validation.py` | 135 | typed request parsing, unknown-field rejection, draft arrays |
| `calc.py` | 300 | 9 calculations (grade tables, net weight variants, protein basis, fees, score, bias) |
| `services.py` | 515 | shared domain layer: gates, portion accounting, ledger, cascades, expiry sweep |
| `routes_config.py` | 604 | 26 endpoints: clock, areas, fee schedules, applicants/payments, inspectors, equipment, comparison checks |
| `routes_ops.py` | 589 | 19 endpoints: requests, samples, grading results, protein analyses, weighing records |
| `routes_final.py` | 706 | 19 endpoints: certificates, appeals, appeal votes, vessel watches |

## Endpoint count

**64 routes, an exact match to SCAFFOLD.yaml** — I diffed the implemented `url_map` against every `method`/`path` pair in the spec: 0 missing, 0 extra.

## Boot confirmation

`bash start.sh` boots cleanly and serves. Verified with two full end-to-end suites, each against a fresh `start.sh` boot, both reporting **0 failures** and **0 server-side tracebacks**:

- **Suite 1** (~90 assertions): area → 5 fee schedules → applicant → 4 inspectors (training/activate) → 3 equipment (certify) → request → sample → grading (`US_NO_2`, limiting factor `TEST_WEIGHT`) → weighing (dockage 3081 / net 202119 / provisional 202122 / variance 3 / 3609.27 bu) → supervise → COMBINED certificate (fee **44850**, deadlines +5d/+10d) → payment waterfall → appeal filing with OCC 412 → sample assignment → regrade → 3 panel votes → `DECIDED_REVISED` (full deposit refund, prior cert VOIDED+REVERSED, fee-free `APPEAL_GRADE` cert, inspector score 100→84) → conserved ledger → auth 401/403, pagination, 404 → clock sweep (3 equipment EXPIRED) → monotonic-clock 422.
- **Suite 2** (~80 assertions): fee-schedule window conflicts, per-area unique asset codes, `ERR_EXPIRY_IN_PAST`, comparison checks (DRIFT_WATCH → cyclic recovery → OUT_OF_TOLERANCE), protein analysis on instrument basis (33.90 / −0.70) then recompute to official basis (34.84 / +0.24), scale capacity guard, vessel-watch lifecycle (45-min buffer overlap, area capacity, `ERR_HOLDS_NOT_FULLY_SUPERVISED`, 90 supervision minutes), `EXPORT_CARGO` certificate with overtime (fee **76000**), `ERR_CREDIT_LIMIT_EXCEEDED`, the full calibration cascade (analysis → `REJECTED_CALIBRATION`, portion released, certificate VOIDED + fee REVERSED, ledger back to 0), recalibration recovery, break-seal, suspend/reinstate/revoke with watch abort, area suspension blocking intake, list filters, 405.

Storage is in-memory only (Python dicts in `store.py`); nothing is seeded at startup — Suite 1's assertion that a fresh boot has exactly 4 inspectors and 0 appeals only holds with an empty initial state.

Two spec details worth flagging, both resolved in favor of the SCAFFOLD: `portions_available` is pure arithmetic (`count − consumed − retained`) and is *not* zeroed when a sample goes BROKEN (the BROKEN gate is the separate rung-9 `ERR_SAMPLE_INTEGRITY_BROKEN`); and on `weighing-records/{id}/supervise`, `ERR_SELF_SUPERVISION_FORBIDDEN` correctly precedes `ERR_ENDORSEMENT_MISSING` per the rung-10 ordering.

## Step 5: Generate unit tests — 2026-09-01T12:16:18.000Z

Generation is complete. Both stages are finished and verified.

## Files created

**`/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/test_helpers/`** (9 files)
`__init__.py` (barrel), `api_client.py` (`/grain-inspection` prefix, all 14 collections + nested/action routes), `api_errors.py` (65 `ApiErrorId` members + status map), `constants.py` (clock anchors, grade tables, factor sets, the six-draft corn fixture), `factories.py` (payload builders), `fixtures.py` (three tiers: primitives → composites `setup_office`/`setup_sampled_request`/…/`setup_appeal_under_review` → read-backs), `assertions.py` (ledger, portion, tally, score invariants), `test_users.py` (five roles + anonymous/unknown headers), `types.py`.

**`/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/test_suite/`** (`conftest.py` + 16 test modules)
Queue B: `test_01_requests_and_samples.py` (9), `test_02_lifecycle_state_machines.py` (7), `test_03_fees_and_scores.py` (5), `test_04_validation_rules.py` (16), `test_05_endpoint_behaviour.py` (5), `test_06_access_control_and_not_found.py` (6), `test_07_concurrency_and_visibility.py` (3). Queue A: `test_08` (5), `test_09` (7), `test_10` (4), `test_11` (5), `test_12` (4), `test_13` (4), `test_14` (6), `test_15` (6), `test_16` (7).

## Test count and coverage audit

- **99 tests**, all collected by pytest (`99 tests collected in 0.56s`), every module compiling.
- **70 non-stub design instances translated, 0 skipped**: 19 of 19 difficulty rules' instances (48 tests, every instance ≥2) and 51 of 51 corner instances (51 tests, every instance ≥1). 18 stub/excluded instances correctly carry no tests.
- Tag audit: exactly one `Design:` line, last line of every docstring; no orphan tags, no dual tags, no tags on stub instances.
- Citation audit: `problems: 0` — every docstring sentence is a verbatim, non-abbreviated PRD sentence.
- No `skip`/`xfail`/placeholder/TODO anywhere; no reference to the design documents in comments.

## Partial translations and PRD-first corrections (design vs PRD conflicts, PRD wins)

1. `Corner/rbac/self_supervision_and_self_check_are_both_refused` — only the self-supervision half is testable. PRD §2.1 states the acting inspector is "always named explicitly in the request body … never inferred from the header", and the comparison-check body carries no filer field, so `ERR_SELF_CHECK_FORBIDDEN` is undecidable for a conforming implementation; that probe was dropped and replaced with the derivable "instrument untouched" + "a second supervisor succeeds" assertions.
2. Comparison-check response shape is unspecified (no ComparisonCheck entity anywhere), so tests assert 201 on the POST and then read the Equipment row for `approval_status`, `rolling_bias_pct`, `recent_deviations_pct`, `comparison_check_count`.
3. `ERR_DUPLICATE_PANEL_VOTE` asserted as 422 (design said 409 — the PRD status table says 422).
4. Sub-assertions dropped as not uniquely derivable: `available_credit_cents` (field does not exist in the PRD), the per-request `sequence_no` triple (`sequence_no` is per **applicant**), empty-PATCH-body → 422, and the payment endpoint's response body shape (asserted via an immediate applicant read instead).
5. The ambiguous COMBINED-certificate probe was re-pointed at a WEIGHT certificate, and a "missing GRADING" probe asserts `ERR_SERVICE_NOT_REQUESTED`, per the §2.11 rung order.

Throughout, no sibling task directory and no `workspace/implementation/` file was read.

## Step 7: Run tests and iterate — 2026-09-01T12:37:33.000Z

All 8 parallel rounds now pass 99/99.

## Summary

**Iterations run:** 2 (each an 8-round concurrent sweep, `per-test-server` isolation). Iteration 1: 92/99 in all 8 rounds, 7 deterministic failures (no flakiness — the union equalled every round's set). Iteration 2: 99/99 in all 8 rounds.

**Tests deleted:** none deleted outright. Two assertions were removed under STEP 1c partial-coverage handling (their host tests retain their PRD-covered assertions):

1. `test_02_lifecycle_state_machines.py::test_a_grade_certificate_is_refused_while_the_request_is_only_sampled` — dropped the trailing `WEIGHT`-certificate-on-a-`GRADING`-only-request probe expecting `ERR_SERVICE_NOT_REQUESTED`. **ERROR PRECEDENCE SILENCE**: §2.11 rung 7 lists `ERR_SERVICE_NOT_REQUESTED` as guarding "certificate issuance", but §3.4's closing enumeration is closed and names only "`EXPORT_SUPERVISION` for a vessel watch or an export cargo certificate" for the certificate case, while §3.8 assigns the missing-weighing-record case to `ERR_WEIGHING_SUPERVISION_REQUIRED` (rung 9). Both readings are PRD-faithful; the implementation's `ERR_WEIGHING_SUPERVISION_REQUIRED` stands. (Scaffold rule that drove it: `Corner/state_machines/certificate_cannot_be_issued_before_a_final_grading_result_exists`.)
2. `test_14_cross_entity_state.py::test_countersignature_refuses_the_weigher_and_an_inspector_from_another_area` — dropped the out-of-area-supervisor probe expecting `ERR_SERVICE_AREA_MISMATCH` on countersignature. **PRD SILENCE on applies_to**: rung 7 enumerates `ERR_SERVICE_AREA_MISMATCH` as guarding exactly "sample creation, weighing-record creation, protein-analysis creation and certificate issuance" — countersignature is not in the set, and §3.6's countersignature paragraph names only the self-supervision, endorsement and `ACTIVE`-licence gates. (Scaffold rule: `Difficulty/cross_entity_state_dependency/weight_certificate_legality_depends_on_area_supervision_flag_and_weighing_state`.)

**Fixes applied to `test_helpers/`:** none — the shared fixtures/factories were consistent with PRD.

**Fixes applied to `test_suite/`:**
- `test_06_access_control_and_not_found.py` — `close_watch_payload(3)` → `close_watch_payload(3, True)`. The factory requires `stowage_certified` (both fields are reported on closure per §3.7); the missing argument raised a `TypeError` before the request was ever issued.

**Fixes applied to `implementation/`:**
- `routes_config.py`, `file_comparison_check` — return `201` instead of `200`. A comparison check is a persisted resource: §3.3 counts them (`comparison_check_count`) and the out-of-tolerance cascade orders analyses relative to "the instrument's previous comparison check", so §4's "Operations that create a new resource return 201 Created" applies; it is not one of §4's 200-returning action endpoints (no `{id}` in the path).
- `store.py`, `parse_dt` — reject client-supplied timestamps that lack a `T` designator or an explicit zone designator (previously a naive value like `2026-08-03 09:00` was silently accepted and coerced to UTC, so a malformed clock value surfaced as `ERR_CLOCK_NOT_MONOTONIC` at rung 12 instead of `ERR_INVALID_REQUEST` at rung 5).
- `routes_final.py`, `start_vessel_watch` — evaluate the watch's own state gate before the holder's licence gate. Rung 9's headline rule is "the entity must be in a state the requested action is declared from", and `ERR_INSPECTOR_LICENSE_INVALID`'s rung-9 scope is "every write naming an inspector" — the start endpoint names none in its body — so starting a terminal `ABORTED` watch must report `ERR_INVALID_STATE_TRANSITION`.

No implementation check required by PRD was removed or weakened; no endpoint, field or side effect was added; storage remains in-memory dicts with no startup seeding.

**Orchestrator note:** the subagent's `results.{1..8}.json` artifacts were not left on disk, so the orchestrator re-ran the identical 8-round `per-test-server` sweep independently to verify the 99/99 claim and regenerate the artifacts. Independent sweep result (2026-09-01T12:48:22Z): `results.1..8.json` each report **99 / 99**.

## Step 8: Finalize PRD — 2026-09-01T12:48:22.000Z

`PRD_FINALIZED.md` written with six inline edits, one per Step 7 finding (plus one companion sentence for the certificate-precedence finding).

## Line counts
- `PRD.md`: 434 lines / 95,340 bytes
- `PRD_FINALIZED.md`: 434 lines / 96,526 bytes
- Line delta: 0 (+0.0%); byte delta +1,186 (+1.24%) — every edit is an inline clause inside an existing sentence/paragraph. No new sections, no reordering.

## Changes
- **§2.10 (territoriality)** — insert — the `ERR_SERVICE_AREA_MISMATCH` check is carried by exactly the four operations rung 7 enumerates and no others; countersignature does not test the supervisor's area — `routes_ops.py:543-555` (no `assert_same_area` in `supervise_weighing_record`)
- **§2.11 rung 5 (Schema)** — insert — a client-supplied instant must carry both a `T` designator and an explicit zone designator (`Z` or numeric offset, normalised to UTC); a looser value is `ERR_INVALID_REQUEST` at this rung, never coerced to UTC — `store.py:63-83`, `validation.py:85-89`
- **§2.11 rung 7** — revise — `ERR_SERVICE_NOT_REQUESTED` guards certificate issuance "for the `EXPORT_CARGO` type alone" — `routes_final.py:63-64`
- **§3.3 (comparison programme)** — insert — a comparison-check filing answers `201 Created`, `data` carrying the updated instrument row — `routes_config.py:607`
- **§3.7 (standing the watch)** — insert — the watch's own state is the first gate; a non-`SCHEDULED` watch is `ERR_INVALID_STATE_TRANSITION` before licence, endorsement or window — `routes_final.py:635-640`
- **§3.8 (certificate gates)** — revise — "falling short" for the operative-weighing gate explicitly includes a request that never ordered `WEIGHING` — `routes_final.py:78-84`

## Pre-edit search log

**1. §3.3 comparison-check status code.** (a) Subject: HTTP status + response body of `POST /comparison-checks`. (b) Enumerated: `routes_config.py:592-607` (only raise/return site), `envelope.py:28-34` (`created` = `ok(..., 201)`), grepped all 12 `created(` callsites to confirm no other 200/201 ambiguity was touched, confirmed no `db.comparison_checks` collection and no GET endpoint for checks (`store.py:14-29`, §4 table). (c) Adjustment: dropped my first draft's "creation of a check *record*" phrasing — no check row is persisted — and instead said "the recording of a new check … its `data` carries the updated instrument row", which matches `return created(serialize(instrument))` exactly.

**2. §2.11 rung 5 timestamp strictness.** (a) Subject: accepted lexical form of every client-supplied instant, not just `current_utc`. (b) Enumerated all seven `{"type": "datetime"}` fields — `current_utc` (`routes_config.py:40`), `effective_from`/`effective_to` (`:132-133`), `license_expires_at` (`:307`), `certified_until` (`:503`), `window_start_at`/`window_end_at` (`routes_final.py:566-567`) — plus the single chokepoint `validation._coerce` → `store.parse_dt`. Confirmed `parse_dt` also rejects non-strings and empty strings, and that offsets are converted with `astimezone(utc)`. (c) Adjustment: placed the rule at rung 5 (not in §2.5) because it applies to every datetime field, not just the clock; added "which is then normalised to UTC" so the accepted `+02:00` path is not accidentally excluded by the wording.

**3. §2.11 rung 7 `ERR_SERVICE_NOT_REQUESTED` scope.** (a) Subject: which writes/certificate types raise `ERR_SERVICE_NOT_REQUESTED`. (b) Grepped every raise site: `routes_ops.py:83` (request creation, missing `GRADING`), `:388` (`PROTEIN`), `:495` (`WEIGHING`), `routes_final.py:575` (watch, `EXPORT_SUPERVISION`), `routes_final.py:63-64` (certificate — `EXPORT_CARGO` only); `services.py:104-106` is the only helper. Also confirmed `routes_final.py:118` merely *skips* protein snapshotting when `PROTEIN` is unordered rather than raising. (c) Adjustment: scoped the qualifier to the certificate item only, leaving the other four entries verbatim so the `PROTEIN`/`WEIGHING`/watch paths keep their guard.

**4. §3.8 operative-weighing "falling short".** (a) Subject: the error for a `WEIGHT`/`COMBINED`/`EXPORT_CARGO` certificate with no operative record. (b) Enumerated `routes_final.py:77-84` (`weighing_record is None` → `ERR_WEIGHING_SUPERVISION_REQUIRED`; `needs_supervision` = area flag **or** `EXPORT_CARGO`), `services.py:363-371` (`operative_weighing_record` = `WEIGHED`/`SUPERVISED` only, so a `VOIDED` record after the scale cascade also lands here), `services.py:272-297` (cascade that produces that state), `routes_ops.py:495` (weighing-record creation still raises `ERR_SERVICE_NOT_REQUESTED`, unchanged). (c) Adjustment: worded as an additive "including on a request that never ordered `WEIGHING`" so the sentence still covers the `VOIDED`-record and `WEIGHED`-but-supervision-required cases, and left the `EXPORT_CARGO`-always-countersigned rule (later paragraph) untouched.

**5. §3.7 watch-start gate order.** (a) Subject: ordering of the state gate against licence/endorsement/window at `POST /vessel-watches/{id}/start`. (b) Enumerated every same-rung-9 ordering site to make sure I did not generalise: `routes_final.py:635-640` (start: state → licence → endorsement → window), `:658-661` (close: state first, no licence), `:682` (abort: state first), `routes_ops.py:550-555` (**supervise: licence *before* state**), `:497-505` (weighing creation: area → equipment → licence → state), `:277-285` (grading: licence → state), `routes_final.py:66-106` (issuance: area → licence → under-appeal → weighing → watch → grading → prior). (c) Adjustment: this is why the sentence is confined to the watch-start endpoint — an earlier draft phrased it as a general "state precedes licence" rung-9 rule, which would have contradicted `supervise_weighing_record` and grading-result creation. Also spelled out the three non-`SCHEDULED` states so the claim matches `row["status"] != "SCHEDULED"` exactly.

**6. §2.10 territoriality applies_to.** (a) Subject: which operations enforce `service_area_id` equality. (b) Enumerated all `assert_same_area` callsites (`routes_ops.py:158-159`, `384-385`, `491-492`, `routes_final.py:62`) and every write naming an inspector/equipment that does **not** call it: `supervise_weighing_record` (`routes_ops.py:543`), `create_grading_result` (`:241`), `break_sample_seal` (`:223`), `recompute_protein_analysis` (`:429`), `file_comparison_check` (`routes_config.py:583`), `create_vessel_watch` (`routes_final.py:560`, area copied from the request), `cast_appeal_vote` (`routes_final.py:470`). (c) Adjustment: my first draft said "no other write tests the named inspector's area" — that would mis-describe `cast_appeal_vote`'s `BOARD_APPEAL` composition rule at `routes_final.py:513-515`, which *does* compare areas (with `ERR_BOARD_PANEL_COMPOSITION_INVALID`). Rewrote to "the operations that carry **this check** … and no others", which speaks only to `ERR_SERVICE_AREA_MISMATCH` and leaves §3.9's board-panel rule intact.

## Step 9: Complete PRD — 2026-09-01T13:08:18.000Z

All planned edits are applied. `PRD_COMPLETED.md` is complete.

## Counts

- `PRD_FINALIZED.md`: 434 lines, 96,526 chars — `PRD_COMPLETED.md`: 434 lines, 104,000 chars (**char delta +7,474**; line count unchanged, every edit is an in-paragraph insert or revision, no new sections/paragraphs)
- 47 PRD lines touched, **67 changes: 53 ambiguity-pins, 14 mismatch-revisions**

Absolute paths: source `/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/workspace/PRD_FINALIZED.md`, output `/home/ubuntu/github/CodingPRD/tasks/task_2233_official_grain_inspection_weighing/workspace/PRD_COMPLETED.md`, implementation under `.../workspace/implementation/`.

## Changes

- §2.1 — revise — mismatch — PRD claimed the server never compares `X-User-Id` to an `Inspector` row `id`; a non-canonical, non-applicant header that is an Inspector row id authenticates, resolving to `SupervisingInspector` when `SUPERVISION` is endorsed else `LicensedInspector`, anything else `ERR_UNAUTHENTICATED` — auth.py:44-54
- §2.1 — revise — mismatch — applicant scope binds only when the header is itself an `Applicant` row `id`; canonical `applicant_user` carries no account and passes every scope test — auth.py:34-42, auth.py:71-79
- §2.1 — insert — ambiguity — collection endpoints narrow the window silently instead of refusing — routes_ops.py:35-46
- §2.3 — revise — ambiguity — `offset` has no upper bound; either parameter as empty string reads as absent; non-integer or out-of-range is `ERR_INVALID_REQUEST` (422) — envelope.py:46-58
- §2.3 — insert — ambiguity — filters compare the field to the raw value as text (booleans also `true`/`1`, `false`/`0`), never match a null field, empty filter ignored, unlisted query params ignored — envelope.py:66-83
- §2.5 — revise — ambiguity — sweep order is `sequence_no` only for entities carrying one, else write order; an instant exactly equal to `current_utc` counts as passed — services.py:483-510
- §2.7 — revise — ambiguity — `expected_certificate_version` must be a non-negative integer — routes_final.py:227-233
- §2.7 — revise — ambiguity — `expected_appeal_version` is a required non-negative integer — routes_final.py:472-478
- §2.8 — revise — ambiguity — a certificate whose fee was 0 still flips to `REVERSED` and credits nothing — services.py:260-270
- §2.8 — revise — ambiguity — cascades reverse only certificates still `ISSUED` or `UNDER_APPEAL`; `VOIDED`/`SUPERSEDED` rows are left untouched — services.py:272-298
- §2.9 — revise — mismatch — the self-check test compares the caller's `X-User-Id` to the body `inspector_id`, so it bites only when the caller uses their own Inspector row id — routes_config.py:560-562
- §2.11 — insert — ambiguity — where the account is named by a body field, schema parse precedes the scope test, so a rung-5 failure surfaces first; scope still precedes rung-6 existence on that field — routes_ops.py:59-70, routes_final.py:223-235
- §2.11 — revise — ambiguity — multiple body FKs resolve in the order §3 introduces them, indirect rows (request's area/applicant) last — routes_ops.py:59-90
- §3.1 — revise — ambiguity — service-area PATCH accepts any subset, leaves omitted/null fields as they stand, and always advances `updated_at`/`version` — routes_config.py:98-113
- §3.1 — insert — ambiguity — `base_fee_cents` is required — routes_config.py:128
- §3.1 — revise — ambiguity — `contact_email` is any non-empty string, form never validated — routes_config.py:211
- §3.2 — revise — ambiguity — `endorsements` holds at most five entries with repeats collapsed — routes_config.py:300-322
- §3.2 — revise — ambiguity — licensing does not require `license_expires_at` in the future — routes_config.py:307
- §3.2 — revise — ambiguity — training `hours` strictly >0 and ≤1000 — routes_config.py:415
- §3.2 — revise — ambiguity — `training_hours_completed` held to 2 decimals — routes_config.py:419-421
- §3.2 — insert — mismatch — training filing exposes no resource: `200 OK` with the updated inspector row — routes_config.py:425
- §3.2 — revise — ambiguity — activation (and manual suspension/reinstatement/revocation) from outside its source states is `ERR_INVALID_STATE_TRANSITION` before qualification/expiry tests — routes_config.py:350-361
- §3.2 — insert — ambiguity — `suspension_reason` required on suspension — routes_config.py:366-371
- §3.2 — insert — ambiguity — `suspension_reason` required on revocation — routes_config.py:395-400
- §3.3 — revise — ambiguity — `division_size_lbs` is a positive integer — routes_config.py:440-455
- §3.3 — revise — ambiguity — `max_capacity_lbs`/tolerance accept zero or more — routes_config.py:440-455
- §3.3 — revise — mismatch — naming a scale-only key on a non-scale counts as supplying it even when the value is an explicit null — routes_config.py:456-462
- §3.3 — revise — ambiguity — certification is accepted from every status but `WITHDRAWN`, including re-certifying `APPROVED`/`DRIFT_WATCH` — routes_config.py:496-516
- §3.3 — revise — mismatch — every passing certification clears `recent_deviations_pct`/`rolling_bias_pct` (not only recovery from `OUT_OF_TOLERANCE`), while `last_comparison_deviation_pct`/`comparison_check_count` stand — routes_config.py:530-534
- §3.3 — insert — mismatch — a failed scale certification is not an error: `200 OK`, row to `OUT_OF_TOLERANCE`, offered `certified_until` discarded, `last_certification_error_lbs` set, counter untouched — routes_config.py:517-527
- §3.3 — revise — ambiguity — scale-failure cascade voids affected certificates oldest first and only still-live ones — services.py:272-298
- §3.3 — revise — mismatch — the cascade resets the weighing dimension from whatever value other than `NOT_REQUIRED` it held, not only `WEIGHT_CERTIFIED` — services.py:290-296
- §3.3 — revise — ambiguity — `reference_value_pct`/`instrument_reading_pct` are percentages 0.0–60.0 — routes_config.py:549-552
- §3.3 — insert — ambiguity — the checked inspector must hold a `PROBATIONARY` or `ACTIVE` licence (`ERR_INSPECTOR_LICENSE_INVALID`) — routes_config.py:556-559
- §3.3 — insert — ambiguity — neither resolution lifts an instrument already `OUT_OF_TOLERANCE`: counter resets to 0, approval status stays — routes_config.py:585-596
- §3.3 — insert — ambiguity — instrument out-of-tolerance cascade with no prior check covers every analysis on that instrument — services.py:300-315
- §3.3 — insert — ambiguity — that cascade voids only still-live certificates — services.py:316-328
- §3.4 — revise — ambiguity — `requested_services` repeats collapse to one — routes_ops.py:59-95
- §3.4 — revise — mismatch — an `ORIGINAL` sample advances the grading dimension only while the request is still `OPEN` — routes_ops.py:193-198
- §3.4 — insert — ambiguity — a further sample of any type on the same request is accepted and leaves the grading dimension unchanged — routes_ops.py:193-198
- §3.4 — revise — mismatch — break-seal is accepted from `SEALED` or `CONSUMED`; any other state, or a sample an appeal still holds, is `ERR_INVALID_STATE_TRANSITION` (the appeal-hold test applies from both states) — routes_ops.py:228-231
- §3.5 — revise — ambiguity — a grading result off a non-`SAMPLED` request is `ERR_INVALID_STATE_TRANSITION` — routes_ops.py:283-285
- §3.5 — revise — ambiguity — the pre-existing original is what the segregation rules treat as the challenged determination — routes_ops.py:286-289
- §3.5 — insert — ambiguity — an appeal regrade is written `SUPERSEDED` while review is pending — routes_ops.py:317
- §3.5 — revise — ambiguity — the operative-status set covers both the plain final result and a regrade until the appeal is decided for the applicant — services.py:330-372
- §3.5 — revise — ambiguity — "the request's `FINAL` determination" means the most recently created one — services.py:330-340
- §3.6 — insert — ambiguity — a weighing record off a request in the wrong state is `ERR_INVALID_STATE_TRANSITION` — routes_ops.py:500-503
- §3.7 — revise — ambiguity — `open_watch_count` increments with no ceiling — routes_final.py:620
- §3.7 — revise — ambiguity — starting a watch carries no body, so the licence/endorsement examined are the watch's own `supervisor_inspector_id`'s — routes_final.py:627-640
- §3.7 — insert — ambiguity — start offered from any other state is `ERR_INVALID_STATE_TRANSITION`, tested before licence — routes_final.py:636
- §3.7 — insert — ambiguity — the close body's counts are required integers of zero or more — routes_final.py:650-658
- §3.7 — revise — ambiguity — close is accepted only from `IN_PROGRESS`; from a terminal state it is `ERR_INVALID_STATE_TRANSITION` — routes_final.py:659
- §3.7 — insert — ambiguity — `open_watch_count` never drops below 0, the floor every decrement respects — routes_final.py:671-672, 687-688
- §3.8 — revise — ambiguity — a still-`ISSUED` predecessor of the same type with `grade_revision_count` 0 leaves nothing to supersede: `ERR_INVALID_STATE_TRANSITION` — routes_final.py:100-106
- §3.8 — revise — mismatch — weight snapshots are null unless the certificate type asserts weight (always null on `GRADE`/`APPEAL_GRADE`) — services.py:427-470
- §3.8 — revise — ambiguity — the protein snapshot uses the most recent `ACCEPTED`/`RECOMPUTED` analysis and is null when none exists or on a `WEIGHT` certificate — services.py:374-390, 427-470
- §3.8 — revise — ambiguity — where several schedules qualify, the most recently created wins — services.py:228-244
- §3.8 — revise — ambiguity — `overtime_applied` is retained on the certificate row and is false on an `APPEAL_GRADE` — services.py:427-460
- §3.8 — revise — ambiguity — the credit-limit test runs even for the fee-free `APPEAL_GRADE`, where an over-limit balance alone refuses it — routes_final.py:141-142
- §3.8 — revise — mismatch — a zero or negative `amount_cents` is refused with `ERR_PAYMENT_EXCEEDS_ALLOCATABLE`, not as a schema fault — routes_config.py:265-270
- §3.8 — insert — ambiguity — no payment resource is kept; the response carries the updated applicant row — routes_config.py:285-292
- §3.9 — revise — mismatch — appeal-filing scope inspects only the body `applicant_id`; the challenged certificate's account is never compared — routes_final.py:223-235
- §3.9 — revise — ambiguity — a non-`ISSUED` certificate or an `APPEAL_GRADE` one is `ERR_INVALID_STATE_TRANSITION` — routes_final.py:244-245
- §3.9 — revise — ambiguity — the challenged determination for regrade segregation is the request's `FINAL` determination with no appeal linkage; where none remains the regrade proceeds — routes_ops.py:286-289
- §3.9 — insert — ambiguity — voting is not gated on appeal state, and the segregation target falls back to the earliest determination with no appeal linkage — routes_final.py:490-507
- §3.9 — revise — ambiguity — the replacement `APPEAL_GRADE` certificate names the regrading inspector as `issuing_inspector_id` and stays `UNPAID` at fee 0 — routes_final.py:371-381
- §3.9 — revise — ambiguity — dismissal also returns the request's grading dimension `UNDER_APPEAL → GRADE_CERTIFIED` — routes_final.py:431-433
- §4 — revise — mismatch — the 201/200 rule carves out training-record filing, which answers `200 OK` with the inspector row — routes_config.py:408-425

Deliberately not added: `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` framework entries in §5 (routing-layer noise, no behavioural ambiguity in PRD prose).

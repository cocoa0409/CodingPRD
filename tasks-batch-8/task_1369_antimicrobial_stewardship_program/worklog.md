# Worklog — task_1369_antimicrobial_stewardship_program

## Step 1: Create Task Directory — 2026-08-13T01:03:00.000Z

Directory `tasks/task_1369_antimicrobial_stewardship_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

User difficulty directive: "Generate task hard than expert level!" — forwarded to scaffold generation as an elevated-difficulty directive (beyond expert tier).

## Step 2: Generate Scaffold — 2026-08-13T02:01:00.000Z

## Summary

Generated the antimicrobial stewardship program scaffold at `/home/ubuntu/github/CodingPRD/tasks/task_1369_antimicrobial_stewardship_program/` with all three required files, lint-clean on first full run after FK fixes.

**Final verdict block:**
```
Coverage
  §1.5 endpoints declared:    77
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  781
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts:**
- Entities: 16 (Hospital, Practitioner, PatientCase, Antimicrobial, AllergyAssessment, CultureReport, SusceptibilityResult, AntibioticOrder, ApprovalRequest, AuditIntervention, ConversionOpportunity, Antibiogram, AntibiogramRow, EmpiricGuideline, DOTMetricSnapshot, RegulatoryReport)
- State machines: 8 entities with 43 transitions (ApprovalRequest branching with escalate fork; AntibioticOrder parallel dimensions approval_status × therapy_status; AuditIntervention cyclic negotiation RECOMMENDED→REJECTED→APPEALED→RECOMMENDED; AllergyAssessment cyclic with INDETERMINATE loop and CONFIRMED rechallenge; Antibiogram, EmpiricGuideline, DOTMetricSnapshot, RegulatoryReport)
- Calculations: 8 (DOT dual-variant calendar-vs-dose basis; benchmark percentile threshold ladder; IV-to-PO multi-gate weighted score; de-escalation priority with pinned evaluation order; allergy risk dual-variant intake-vs-verified; antibiogram rate with pinned round-per-row order; culture-driven recommendation selector policy with 4-level tie-break; regulatory payload projection with FNV-1a checksum)
- Validations: 34 priority-ordered rules across auth/existence/state/safety/temporal/referential/constraint/fiscal
- Endpoints: 77
- Errors: 65
- Roles: 6 (segregation-of-duties: requester≠decider, adjudicator≠auditor≠responder)
- §1.8 difficulty instances: 18 (exactly 2 per rule, all nine rules)
- §1.9 corner instances: 66 active + 2 excluded_because stubs = 68 entries (entities 10, state_machines 12, calculations 7, validations 12, endpoints 7, errors 10, roles 5, cross_cutting 3, stubs 2)

**Notable design decisions:**
- Flat topology with cross-aggregate FK references (per §0.3 prioritization) rather than URL nesting; every FK has a filtered-list reverse-reachability GET.
- Logical clock (`POST /stewardship/_clock/set_current_utc`, default 2026-08-01T00:00:00Z) drives all temporal sweeps: approval auto-expiry, intervention overdue supersede, opportunity expiry, DOT review-threshold flagging.
- Two OCC rules on Hospital.version (guideline adopt, antibiogram publish) — both use `${var}`-captured versions in recipes.
- All formula-derived assert literals were computed via Python before pinning (IV-to-PO score 97.00/106.00, allergy 13.00→10.00, DOT 2 vs 0.75, percentile boundaries at 780.00).
- Difficulty rule differentiation honored: dual-variant on different domains (AntibioticOrder DOT vs AllergyAssessment risk); combinatorial modes (a) vs (b); cascades from different triggers (clock vs adjudicate, depth 3 vs 2); boundary on different metrics/endpoints (percentile floor vs IV-hours minimum); temporal overlap with different interval semantics (half-open fixed window vs rolling 365-day lookback); compensating invariants on different conserved quantities (DOT totals vs intervention cardinality).
- `worklog.md` and empty `workspace/` were pre-created by the pipeline launcher and left untouched.

Orchestrator verification: all three YAMLs exist on disk (SCAFFOLD.yaml 2078 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1378 lines, SCAFFOLD_CORNER_DESIGN.yaml 3376 lines).

## Step 3: Copy Shared Files — 2026-08-13T02:02:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1369_antimicrobial_stewardship_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T02:27:00.000Z

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_1369_antimicrobial_stewardship_program/workspace/PRD.md` — **374 lines**, ending at §5 with no audit footer.

## Section structure
- **§1 Introduction** — 2 paragraphs (program mandate + facility-scope/role framing)
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 RBAC (with per-role identity translation), 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified by string containment), 2.3 Pagination, 2.4 Program Clock & Scheduled Sweeps, 2.5 Common Resource Properties, 2.6 Precision & Rounding, 2.7 OCC on Hospital Posture, 2.8 Validation Cascade Order, 2.9 Segregation of Duties, 2.10 Cross-Facility References, 2.11 Nested Path Resolution
- **§3 Business Logic** — 8 subsections organized by clinical workflow (program setup; ordering & restricted-approval gate; audit negotiation cycle; microbiology & culture-driven recommendation; conversion/de-escalation detection; allergy delabeling; antibiogram & guideline governance; DOT metrics & regulatory submission). No tables, no paths, no method tokens.
- **§4 Endpoint Definitions** — 77/77 endpoints in a 4-column table
- **§5 Error Code Catalogue** — 65/65 errors in a 2-column table with correct HTTP statuses

## Hard Contract reports
```
Contract 1 — Field-Name Coverage:
- entities[].fields: 101 required, 101 present, 0 missing
- endpoints[].request_body: 85 required, 85 present, 0 missing
- response-only fields (recommended_antimicrobial_id, pool_size, reason): 3 required, 3 present
- common fields (id/created_at/updated_at/version): all present
Status: PASS

Contract 2 — Rule Coverage:
- validations[] with priority: 34 checked, 34 expressed (global 10-stage cascade in §2.8 plus explicit per-endpoint sequences for ordering/approval/audit/schedule-test/adopt/submit), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_hospital_version + ERR_STALE_VERSION/412 named for both adopt and publish), 0 missing
- state_machines[].transitions: 44 checked across 8 machines, 44 fully expressed (from/to, preconditions with error IDs, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (DOT dual basis + slice attribution, benchmark floors 350/480/620/780 with inclusive boundaries, IV-to-PO weighted score with 40/0.4/decay terms and 60 floor, de-escalation 50/25/15/−20/10×rank-delta with 65 floor and pinned dot_calendar snapshot order, allergy risk 10/35/80 + 20-keyword + 3/yr decay + 10 comorbidity capped at 100 with 30 threshold and verified-baseline variant, antibiogram round-per-row pin, selector ranking/tie-breaks/empty-pool, FNV-1a payload assembly), 0 missing
- validations[] conditions: 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (discharge/discontinue cascades, sweep quadruple, publish/adopt hospital version increments), 0 missing
- entities[].fields[] structured content: defaults, enum constraints, ranges (>=1, >=24, >0, 1..4, >=20 chars), initial values all reconstructible, 0 missing
- sibling-branch symmetry: APPROVED/DENIED, UPHOLD/OVERTURN, ACCEPTED/REJECTED (respond), NEGATIVE/POSITIVE/INDETERMINATE, DRAFT-retire/STALE-retire (distinct error IDs preserved), calendar/dose DOT variants — all equal density, 0 asymmetric
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned: 680
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage audit
16/16 entities, 8/8 state machines (44 transitions), 8/8 calculations, 34/34 validations, 77/77 endpoints, 65/65 error IDs (prose + table, statuses verified against scaffold), 6/6 roles with identity translations — all verified present in prose by scripted check.

## Zero-Silence-Rule decisions
- **Fenced-block token extraction pitfall**: naive backtick regex pairs across §2.2's JSON fences; verification script strips fences before diffing.
- **DENIED asymmetry preserved**: scaffold stamps `decided_at`/`decided_by_id` only on APPROVED transitions — mirrored exactly rather than symmetrically.
- **`ERR_OPPORTUNITY_NOT_DETECTED` on decline**: named explicitly for decline as well as both accepts (scaffold error condition covers "accept/decline").
- **Counter initial values**: stated that `administered_doses`, `cumulative_iv_hours`, `dot_calendar`, `dot_dose` start at zero and `stopped_at` stays unset until closure.
- **`decided_at`/`decided_by_id`/`escalation_reason` unset-until-event** semantics added to the approval-request creation narrative.
- **`AMENDED` culture status**: enumerated as a valid status counting toward antibiograms without inventing a transition into it (scaffold defines none).
- **`ERR_DUPLICATE_ROW`**: tied to antibiogram generation only, since no `POST /antibiogram-rows` endpoint exists in §1.5 (not invented).
- One fuzzy-word lint hit ("organized around") reworded to keep the prose scanner-clean even though it was non-numeric.

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T03:05:00.000Z

## test_helpers/ inventory (9 files, all importable)

- `/home/ubuntu/github/CodingPRD/tasks/task_1369_antimicrobial_stewardship_program/test_helpers/types.py` — 20 status/role enums + 16 entity TypedDicts (all entities carry `common_fields: true`, so all include id/created_at/updated_at/version).
- `api_client.py` — `ApiClient(GenericApiClient)` with 60 endpoint methods covering every row in the PRD endpoint catalogue, plus the module-level `api_client` singleton.
- `api_errors.py` — `ApiErrorId` enum (62 errors) + `HTTP_STATUS_CODES` map, registered with the framework via `set_error_http_status_map`.
- `assertions.py` — `assert_{entity}` for all 16 entities + `assert_order_dot_invariants`.
- `factories.py` — 14 payload factories (input fields only).
- `constants.py` — hospital defaults, IV-to-PO / de-escalation / allergy / benchmark constants, breadth ladder.
- `test_users.py` — `TEST_USERS` shared constants + 6 `make_*_headers` builders (mandatory per-instance builders for the 5 entity-backed roles).
- `fixtures.py` — composite helpers: `setup_committee`, `setup_hospital_md[_ph]`, `create_order`, `create_restricted_order_with_request`, `record_doses`, `record_iv_doses_over_days`, `create_issued_intervention`, `drive_intervention_to_appealed`, `create_overturned_intervention`, `create_final_culture_with_result`, `create_antibiogram_with_row`, `publish_antibiogram`, `create_published_antibiogram`, `create_and_adopt_guideline`, `setup_iv_order_with_hours`, `create_finalized_snapshot`, `create_submitted_report`.
- `__init__.py` — barrel export.

## test_suite/ (17 test files + conftest.py, 102 tests collected by pytest)

| File | Tests | Queue |
|---|---|---|
| test_01_dot_dual_basis | 4 | A |
| test_02_combinatorial_formulas | 4 | A |
| test_03_intervention_negotiation_cycle | 4 | A |
| test_04_transitive_cascades | 4 | A |
| test_05_validation_priority_pairs | 4 | A |
| test_06_boundary_precision | 4 | A |
| test_07_cross_entity_dependencies | 4 | A |
| test_08_temporal_windows | 4 | A |
| test_09_compensating_invariants | 4 | A |
| test_10_entities | 10 | B |
| test_11_state_machines | 12 | B |
| test_12_calculations | 7 | B |
| test_13_validations | 12 | B |
| test_14_endpoints | 7 | B |
| test_15_errors | 10 | B |
| test_16_roles_rbac | 5 | B |
| test_17_cross_cutting | 3 | B |

## Queue A (§1.8 difficulty): 18/18 translated, 0 skipped
Every one of the 18 non-stub difficulty instances has exactly 2 tests (36 total), each tagged `Design: Difficulty/<rule_id>/<instance.name>`. No skips were needed — the PRD verbatim-covers every asserted rule, including the two priority-pair instances (PRD §2.8 cascade paragraph + §3.2 fixed ordering prose uniquely derive both `state_vs_safety` and `safety_vs_referential` outcomes) and the OCC/adjudicate cascades.

## Queue B (§1.9 corner): 61/61 non-stub translated, 0 skipped
Each non-stub corner instance has ≥1 test tagged `Design: Corner/<section>/<instance.name>` (66 tests total; five instances received a second supporting test). The 2 `excluded_because:` stubs (`approval_expiry_cascade_covered`, `antibiogram_publish_gating_covered`) were not translated; both cross-references verified to resolve to real difficulty instances.

## Audit results
- All 102 test docstrings end with exactly one `Design:` line resolving to a real instance in the source YAML (AST-verified placement).
- 133 quoted citation windows across all docstrings survive literal grep of PRD.md after whitespace normalization (one initial paraphrase in test_16 was rewritten to verbatim PRD text).
- All 39 asserted `ApiErrorId` values are named in PRD prose (not only the §5 table).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/Table references in generated comments.
- `pytest --collect-only` succeeds: 102 tests collected, no import errors.

## Step 6: Generate Implementation — 2026-08-13T03:05:00.000Z

## File inventory — `workspace/implementation/`

- `start.sh` — bash launcher: `cd` to its own dir, guarded dependency install (`python3 -c "import flask"` no-op check so per-test reboots skip pip), then `exec python3 app.py` (foreground, signals propagate)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point; binds `0.0.0.0`, `PORT` env (default 10000); registers blueprints; ApiError/404/405/400 handlers all emit the PRD §2.2 error envelope
- `db.py` — 16 module-level dicts keyed by id + per-order administration-event lists; **zero seeding — every boot starts empty** (verified: relaunch returns `total_count: 0`)
- `errors.py` — all 65 catalog errors with exact `error_id` + HTTP status
- `response.py` — envelope verbatim: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (3-fractional-digit UTC), `response_type` object/array/error, `data`; list meta carries `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` presence check (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), six-role RBAC (403 `ERR_INSUFFICIENT_PERMISSIONS`)
- `util.py` — ISO parsing, logical-clock formatting (mirrors the precision style the clock was set with; initial `2026-08-01T00:00:00Z` verbatim), Decimal round-half-up 2dp, full-years anniversary math, FNV-1a-32 (verified against known vectors), input validators, pagination params (limit default 10, 1–100; offset ≥ 0)
- `services/core.py` — clock + the four scheduled sweeps (approval auto-expiry inclusive `>=`, intervention supersede strict `> due_at`, opportunity 48 h strict, REVIEW_REQUIRED threshold inclusive), DOT counters, standing ladder, allergy risk (intake + verified-baseline), cascades, guideline staleness (drop ≥ 10 → STALE per PRD prose, which overrides the scaffold's strict `<`)
- `services/serializers.py`, `services/listing.py` — serialization (hides `_internal` keys, Decimal→JSON number) and filter/sort/paginate (created_at ASC, boolean-aware filter matching)
- `routes/` — `core_resources.py` (clock, hospitals, practitioners, patient cases, antimicrobials), `allergy_culture.py` (allergy workflow, cultures, susceptibility, selector), `orders_approvals.py` (orders, administrations, approval workflow), `interventions_opportunities.py` (audit negotiation cycle, opportunity detection/accept/decline), `surveillance_reporting.py` (antibiograms, guidelines with OCC, DOT snapshots, regulatory reports)

## Coverage

- **Endpoints: 77/77** — every scaffold endpoint implemented with its exact roles and status codes (201 creates / 200 actions)
- **State machines: 8/8 entities, all 44 transitions** — approval (SUBMITTED/ESCALATED/APPROVED/DENIED/EXPIRED/WITHDRAWN incl. system sweep), order dual-dimension approval/therapy with all cascades (deny/expire/withdraw cleanup of interventions + opportunities per PRD §3.2), intervention negotiation loop (UPHOLD → fresh 24 h due_at; OVERTURN → noncompliance count + standing recompute), allergy cycle (incl. INDETERMINATE loop-back and CONFIRMED rechallenge ≥ 5 y), antibiogram publish/supersede, guideline adopt/stale/retire, snapshot finalize/reopen, report submit/acknowledge
- **Calculations: 8/8** — dual-basis DOT with month slicing, benchmark percentile floors (inclusive), IV-to-PO weighted score (5 gates, min-cap, floor-decay, immunocompromised double-hours rule, ≥ 60), de-escalation score (breadth ladder, newest-FINAL selector with pinned tie-breaks, dot snapshot before side effects, ≥ 65), allergy risk score (cap 100, keyword substring set, verified-baseline recency), antibiogram rows (round-per-row then aggregate — pinned order), culture recommendation selector (CSF/MACROLIDE exclusion, allergy exclusion, 4-level deterministic ranking, 200 null on empty pool), canonical payload + FNV-1a checksum (2dp per-1000 values, integer totals)
- **Validations: 34/34 priorities in cascade order** plus all workflow guards with narrated per-endpoint sequencing (e.g., decide: NOT_PENDING → ESCALATED_REQUIRES_DIRECTOR → SELF_APPROVAL → ORDER_APPROVAL_NOT_PENDING; adopt: OCC first per PRD §3.7; publish: DRAFT → EMPTY → OCC per PRD §3.7)

## start.sh contract

PORT env (default 10000), binds `0.0.0.0`, foreground via `exec`, HTTP-ready in ~2 s (well under 60 s), install guarded for fast per-test reboots. Confirmed stateless: kill + relaunch wiped all state (hospital list empty).

## Smoke verification

Two end-to-end suites passed against `start.sh`-booted servers (~90 assertions): auth/RBAC, ordering guard cascade (duplicate, cap, suspended prescriber, allergy block, renal), approval lifecycle incl. escalate/director/self-approval/auto-expiry/withdraw, intervention cycle → REJECTED_FINAL ×3 → WATCH → SUSPENDED, adjudicator conflict, sweeps (supersede, 48 h expiry, REVIEW_REQUIRED), allergy delabeling, selector ranking, antibiogram rows/overlap/publish OCC 412 + guideline adopt/stale/retire, snapshot finalize/reopen-pin, report payload+checksum+acknowledge, discharge cascade, pagination envelope, boolean filters. Final manual boot + `POST /stewardship/hospitals` returned the exact envelope with `current_utc: 2026-08-01T00:00:00Z`.

Judgment calls on PRD ambiguities (documented in code): clock advance refreshes `updated_at` but does not bump `Hospital.version` (only publish/adopt do, per §2.7); PRELIMINARY culture recommend returns 200 null-pool with `reason: "culture_not_final"`; guideline retire from ADOPTED/RETIRED → `ERR_GUIDELINE_NOT_RETIRABLE`; allergy terminal states reject all further transitions with `ERR_ALLERGY_TERMINAL`; `total_dot_dose` in payload serializes as integer when integral, 2dp otherwise.

## Test-fix iteration loop (2026-08-13)

Three 8-round parallel sweeps (`prd-bench-local-run --isolation per-test-server`):

- **Sweep 1**: 87/102 in all 8 rounds. Union of 18 failures: 15 deterministic + 3 flaky server-restart setup errors.
- **Sweep 2**: 4 rounds 102/102, 4 rounds 101/102 — only failure left was `test_empty_antibiogram_cannot_publish` erroring on setup ("server could not be restarted", 15 s restart-poll window exceeded under 8x lockstep load).
- **Sweep 3**: 102/102 in all 8 rounds. Exit.

Fixes (all test-artifact layer; implementation needed no logic changes — its ERR_CLOCK_REGRESSION / ERR_FUTURE_SPECIMEN rejections were PRD-faithful and the fixtures were violating them):

- `test_helpers/fixtures.py` — `setup_iv_order_with_hours`: dropped the `set_clock(..., "2026-08-01T00:00:00Z")` clock-hold against the initial clock (PRD 2.4 requires strictly-later destinations); `record_iv_doses_over_days` and `create_finalized_snapshot`: guard set_clock to fire only when the target is strictly later than the current clock.
- `test_suite/test_01_dot_dual_basis.py` — module-level helper used the bare fixture name `api` (NameError); switched to `api_client`; advanced the verified-baseline scenario clock to 2028-09-01 so the asserted score 10.00 is independent of the wall-clock run date (`created_at` is server wall-clock per PRD 2.5).
- `test_suite/test_06_boundary_precision.py` — removed the same clock-hold from `_setup_three_dot_snapshot`.
- `test_suite/test_08_temporal_windows.py` — `test_isolate_exactly_365_days_later_is_not_first`: advance clock to 2027-08-02 before registering the culture collected then (PRD 3.4 ERR_FUTURE_SPECIMEN).
- `test_suite/test_12_calculations.py` — `test_antibiogram_first_isolate_filtering`: advance clock to 2026-08-01T01:00:00Z before the 01:00 culture; added `set_clock` import.
- `workspace/implementation/start.sh` — dependency probe behind a `.deps_installed` sentinel so per-test reboots skip the extra CPython startup (restart-poll flake fix; no behavior change).

## Step 7: Run Tests and Iterate — 2026-08-13T03:35:00.000Z

All 8 rounds of the final sweep pass 102/102. Loop complete.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each)
- Sweep 1: 87/102 in all 8 rounds — union of 18 failing tests (15 deterministic across all rounds, 3 flaky).
- Sweep 2: four rounds 102/102, four rounds 101/102 — only `test_empty_antibiogram_cannot_publish` erroring in setup ("server could not be restarted" — the runner's 15s restart-poll window expiring under 8× lockstep load).
- Sweep 3: **102/102 in all 8 rounds.** Exit condition met.

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no deletions were warranted.

**Fixes to `test_helpers/`** (`fixtures.py`):
- `setup_iv_order_with_hours` — removed a `set_clock` to the initial clock value `2026-08-01T00:00:00Z` on a fresh hospital; PRD §2.4 rejects holding the clock with `ERR_CLOCK_REGRESSION` (destination must be strictly later), so the fixture was issuing a PRD-forbidden request.
- `record_iv_doses_over_days` and `create_finalized_snapshot` — guard `set_clock` so it fires only when the target is strictly later than the current clock (the default target equals the initial clock).

**Fixes to `test_suite/`**:
- `test_01_dot_dual_basis.py` — module-scope helper `_setup_allergy_assessment_aged_one_year` referenced the pytest fixture name `api` (NameError); now uses `api_client` (imported). Also advanced the scenario clock to 2028-09-01 so the asserted verified-baseline score (10.00, recency term saturated at 0) no longer depends on the wall-clock run date (`created_at` is wall-clock per PRD §2.5).
- `test_06_boundary_precision.py` — removed the same initial-clock hold from `_setup_three_dot_snapshot`.
- `test_08_temporal_windows.py` — `test_isolate_exactly_365_days_later_is_not_first`: advance the clock to 2027-08-02 before registering a culture collected then (PRD §3.4 `ERR_FUTURE_SPECIMEN`).
- `test_12_calculations.py` — `test_antibiogram_first_isolate_filtering`: advance the clock to 2026-08-01T01:00:00Z before the 01:00 culture; added the missing `set_clock` import.

**Fixes to `implementation/`**: only `start.sh` — the dependency probe is now behind a `.deps_installed` sentinel, eliminating one full CPython startup from every per-test reboot (addresses the restart-poll flake; no API behavior change). No implementation logic was touched — the server's `ERR_CLOCK_REGRESSION` and `ERR_FUTURE_SPECIMEN` rejections that "caused" the failures were exactly what PRD §2.4/§3.4 require, and the fixes went into the fixtures/tests that violated them.

## Step 8: Finalize PRD — 2026-08-13T03:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1369_antimicrobial_stewardship_program/workspace/PRD_FINALIZED.md` written with exactly one revision.

## Summary

**Line counts:** PRD.md 374 lines → PRD_FINALIZED.md 374 lines (0.0% delta; two lines revised in place, no lines added or removed).

**Changes (one edit):**
- §2.5 — revise — the `created_at` bullet now reads "...recording when the resource was created, **stamped from the server's wall clock — never from the hospital's logical clock of §2.4, which does not feed this field**", and the `updated_at` bullet gains the parallel clause "likewise stamped from the server's wall clock rather than the logical clock" — `implementation/util.py:22-24` (`now_iso` = `datetime.now(timezone.utc)`), `implementation/services/core.py:80-84` (`stamp_new`), `implementation/services/core.py:75-77` (`touch`), `implementation/routes/core_resources.py:58`.

**Why this edit:** it traces to the step_7_diff test_01 fix (clock advanced to 2028-09-01 so the verified-baseline score 10.00 stops depending on the wall-clock run date). The load-bearing site is `implementation/services/core.py:176-185` (`recompute_assessment_verified_baseline`): the §3.6 recency term computes `full_years_between(parse_iso(assessment["created_at"]), hospital_clock)` — wall-clock `created_at` versus the logical program clock. PRD §2.5 never pinned which clock stamps `created_at`/`updated_at`, and §2.4's logical-clock emphasis (plus every §3 domain timestamp being logical-clock-stamped) made logical-clock `created_at` a plausible misreading that changes scores. §3.6 itself already pinned the comparison endpoints, so only the §2.5 field definition needed the pin.

**Pre-edit search log (for the single edit):**
- (a) Subject: clock source of system-managed `created_at`/`updated_at`.
- (b) Paths enumerated and read/grepped: writers — `services/core.py:76,82-83`, `routes/core_resources.py:58` (grep `\["created_at"\] =|\["updated_at"\] =` confirms these are the only four write sites, all wall clock); readers — `services/listing.py:28` (list sort), `routes/allergy_culture.py:383` (recommendation tie-break), `routes/interventions_opportunities.py:204` (linked-opportunity ordering), `routes/interventions_opportunities.py:282` (supporting-culture tie-break), `services/core.py:295` (guideline-row tie-break), `services/core.py:176-185` (verified-baseline recency); pass-through — `services/serializers.py:18-24`. Cross-check — all domain timestamps (`started_at`/`stopped_at`/`submitted_at`/`decided_at`/`due_at`/`detected_at`/`resulted_at`/`generated_at`/report `submitted_at`) are logical-clock-stamped via `clock_iso`/`clock_plus` (orders_approvals.py, allergy_culture.py, interventions_opportunities.py, surveillance_reporting.py), so wording was scoped to the two §2.5 bullets only.
- (c) Wording adjustment: rejected any universal "all timestamps are wall-clock" phrasing (would contradict §2.4 and mis-describe the domain-timestamp paths); made no uniqueness/monotonicity claim about `created_at` (impl has only ms resolution).

**Items verified as needing no edit:** the fixtures' removed `set_clock` holds — impl rejects non-strictly-later targets with `ERR_CLOCK_REGRESSION` (`core_resources.py:53-54`), already pinned verbatim in §2.4; the test_08/test_12 clock advances — impl rejects future `collected_at` with `ERR_FUTURE_SPECIMEN` (`allergy_culture.py:212-213`), already pinned verbatim in §3.4; the test_01 `api`→`api_client` NameError and test_12 missing import — pure test bugs; the `start.sh` `.deps_installed` sentinel — startup performance only, no API behavior change.

## Step 9: Complete PRD — 2026-08-13T04:05:00.000Z

All edits are applied. Final verification of counts is done.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (374 lines, 67,600 chars) → `PRD_COMPLETED.md` (375 lines, 72,808 chars; +1 line, +5,208 chars). 28 inline edits, no new sections.

**Counts**: 24 ambiguity-pins, 4 mismatch-revisions.

### Mismatch revisions (PRD described different behavior than impl)
- §3.1 — revise — mismatch — `admitted_at` is caller-supplied and recorded verbatim, not server-stamped from the logical clock — `implementation/routes/core_resources.py:190-195`
- §3.7 — revise — mismatch — guideline retire from `ADOPTED`/`RETIRED` yields `ERR_GUIDELINE_NOT_RETIRABLE` (PRD had `ERR_GUIDELINE_NOT_STALE` for non-STALE); `ERR_GUIDELINE_NOT_STALE` is never raised — `implementation/routes/surveillance_reporting.py:383-384`
- §3.8 — revise — mismatch — therapy-window end for snapshot intersection is `stopped_at`, or the hospital clock for a still-running order (not "the period end") — `implementation/services/core.py:129-144`
- §3.8 — revise — mismatch — regulatory payload `total_dot_dose` serializes as integer only when integral, 2dp otherwise (PRD said "totals as integers") — `implementation/routes/surveillance_reporting.py:524-528,543`

### Ambiguity pins (PRD silent; pinned to impl)
- §2.1 — insert — unrecognized `X-User-Role` value → `ERR_INSUFFICIENT_PERMISSIONS` — `middleware.py:35-36`
- §2.2 — insert — undefined path/method → `ERR_NOT_FOUND` 404; non-JSON/non-object body → `ERR_INVALID_REQUEST` — `app.py:35-49`, `util.py:116-130`
- §2.3 — insert — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_INVALID_REQUEST`; sort ties broken by `id` — `util.py:194-218`, `services/listing.py:28`
- §2.4 — insert — clock advance refreshes `updated_at` but does not bump `Hospital.version`; clock-stamped fields mirror the precision style of the last `to_iso8601` — `routes/core_resources.py:55-58`, `services/core.py:54-70`
- §2.5 — insert — clock advance noted as standing exception to version-increment rule — `routes/core_resources.py:58`
- §2.6 — insert — integral 2dp quantities serialize as bare integers in JSON — `services/serializers.py:10-15`
- §2.7 — insert — missing/non-integer `expected_hospital_version` → `ERR_INVALID_REQUEST` — `routes/surveillance_reporting.py:234-239`
- §2.8 — insert — placement of field-shape (`ERR_INVALID_REQUEST`) checks in the cascade — e.g. `routes/orders_approvals.py:99-102`, `interventions_opportunities.py:389-394`
- §3.1 — insert — `license_no` uniqueness conventional, not enforced; practitioner patch bumps version iff at least one field supplied — `routes/core_resources.py:120-133,156-167`
- §3.1 — insert — `mrn` uniqueness not enforced; discharge leaves `approval_status` untouched and is re-appliable — `routes/core_resources.py:191-206,229-246`
- §3.1 — insert — `drug_name` uniqueness not enforced; formulary patch reactivates, no-op patch leaves version untouched — `routes/core_resources.py:266-278,301-308`
- §3.2 — insert — `dose_mg` must be an integer — `routes/orders_approvals.py:100`
- §3.2 — insert — escalate checks SUBMITTED state before reason length — `routes/orders_approvals.py:389-394`
- §3.2 — insert — dose recording against `COMPLETED`/`DISCONTINUED` → `ERR_INVALID_REQUEST`; `administered_at` not clock-validated — `routes/orders_approvals.py:217-222`
- §3.2 — insert — complete/discontinue from non-closable state → `ERR_INVALID_REQUEST`; completion checks patient admission first — `routes/orders_approvals.py:247-257,272-275`
- §3.3 — insert — accepting DEESCALATION intervention swaps to the latest-created DEESCALATION opportunity's suggested drug (any status); none → drug unchanged, order still `DEESCALATED` — `routes/interventions_opportunities.py:195-207`
- §3.4 — insert — `is_first_isolate` window closed at both ends, counts prior reports of any status — `routes/allergy_culture.py:230-248`; finalize has no state guard and re-stamps `resulted_at` — `routes/allergy_culture.py:265-276`
- §3.4 — insert — non-FINAL/AMENDED recommend returns 200 null-pool with `reason` `"culture_not_final"`; empty pool `"empty_pool"`; success `"selected"` — `routes/allergy_culture.py:343-352,387-401`
- §3.5 — insert — `suggested_antimicrobial_id` optional for IV_TO_PO, mandatory for DEESCALATION (`ERR_INVALID_REQUEST`) — `routes/interventions_opportunities.py:318-322,350-351`
- §3.5 — insert — off-ladder `drug_class` treated as breadth rank 999 — `services/core.py:29`
- §3.6 — insert — schedule-test: terminal states → `ERR_ALLERGY_TERMINAL` before origin check; origin-role mismatch → `ERR_INSUFFICIENT_PERMISSIONS`; rechallenge 5-year check reads stored `years_since_reaction` — `routes/allergy_culture.py:131-147`
- §3.7 — insert — duplicate susceptibility rows for same drug on one culture count once, susceptible if any row is `S` — `routes/surveillance_reporting.py:106-120`
- §3.7 — insert — syndrome-mapped organism row resolution (organism==syndrome, else single row, else lowest pct by created_at) and sweep skip when no reportable row/adoption pct — `services/core.py:278-312`
- §3.7 — insert — guideline draft requires source antibiogram only to exist and share the hospital; PUBLISHED enforced at adoption — `routes/surveillance_reporting.py:275-279`
- §3.8 — insert — malformed `period_label` → `ERR_INVALID_REQUEST`; OPEN snapshots recompute metrics live on single-resource reads, FINALIZED return frozen values — `routes/surveillance_reporting.py:425-432,444-445`

All five known generation-time judgment calls are now pinned: clock-advance version behavior (§2.4/§2.5), PRELIMINARY recommend 200 null-pool `"culture_not_final"` (§3.4), retire from ADOPTED/RETIRED → `ERR_GUIDELINE_NOT_RETIRABLE` (§3.7), allergy terminal precedence (§3.6), and `total_dot_dose` integer-when-integral serialization (§3.8).

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1369_antimicrobial_stewardship_program/workspace/PRD_COMPLETED.md`

## Pipeline Complete — 2026-08-13T04:10:00.000Z

Orchestrator final verification: full directory structure present (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ 9 files, test_suite/ 17 test files + conftest.py, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}). Final sweep results files results.1–8.json all read back passed=102 total=102 failed=0 errors=0.

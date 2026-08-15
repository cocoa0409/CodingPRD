# Worklog — task_1419_geotechnical_engineering_subsurface

## Step 1: Create Task Directory — 2026-08-13T05:37:00.000Z

Pre-assigned by pipeline launcher: `tasks/task_1419_geotechnical_engineering_subsurface/` with `workspace/` subdirectory already created. Treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T06:35:00.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts
- Entities: **15** (Client, Project, BoringPlan, Subcontractor, RigAssignment, UtilityClearance, Boring, Sample, LabTestOrder, LabTestResult, FoundationAnalysis, Report, ObservationVisit, ChangedConditionClaim, ExplorationAuthorization)
- State machines: **13** (11 entities with lifecycles + cyclic machines on Report PE-review loop, LabTestOrder rerun loop, BoringPlan revise loop, Claim appeal loop, FoundationAnalysis self-loop refresh)
- Calculations: **11** (incl. dual-variant bearing capacity and claim quantum, per-line vs sum rounding lab invoice, pre-discount-tier project fee, tiered drilling cost, USCS decision tree, inclusive-boundary clearance expiry)
- Endpoints: **59** (15 single GETs, 13 filtered-list GETs covering all 18 FKs incl. two self-referential, 30 mutations, 1 `/_clock/set_current_utc` with default `2026-08-01T00:00:00Z`)
- Errors: **35** (auth/existence → state → safety → constraint → temporal → referential → fiscal → OCC 412s)
- Roles: **10** (ClientRep and DrillingSub entity-backed with ownership checks; segregation-of-duties on PE report sealing)
- §1.8 instances (non-stub): **19** — all 9 rules at ≥2 instances, combinatorial_formula at 3 (modes a/b/c); every recipe chain replayed against §1.2/§1.4/§1.6 with precomputed literal asserts (e.g. 4800 vs 6000 psf, 40000 vs 50000 cents, 13600 vs 13599 rounding delta, fee 490000 landing below its own tier)
- §1.9 instances: **37 non-stub** + 5 `excluded_because` stubs, across entities / state_machines / calculations / validations / endpoints / errors / rbac / complexity_layers / consistency_model
- OCC concurrency rules: **3** (plan create, authorization approve/revoke, report issue — all `${var}`-driven, 412)

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (59 endpoints, 15 entities, 19 §1.8 + 37 §1.9 instances, 1187 calls scanned).

## Step 3: Copy Shared Files — 2026-08-13T06:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1419_geotechnical_engineering_subsurface/workspace/INSTRUCTION.md` (1424 bytes). Bash-only step.

## Step 4: Generate PRD — 2026-08-13T07:05:00.000Z

PRD generation complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/workspace/PRD.md` — 325 lines, ~8,300 words. The two forbidden difficulty/corner index files were never opened.

**Sections written:**
- §1 Introduction (2 paragraphs, engagement-lifecycle framing)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity translation (ClientRep→Client, DrillingSub→Subcontractor entity-backed; 8 opaque roles); 2.2 verbatim response-envelope block (verified byte-identical to `section-2.2-response-structure.md`); 2.3 pagination (limit 10/1/100, offset 0, created_at ascending) plus list-filter inventory; 2.4 common properties (UUID id, ISO-8601 3-fractional-digit timestamps, version semantics); 2.5 left-to-right nested retrieval; 2.6 logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock, EXPIRED sweeps); 2.7 OCC (all 3 rules with endpoint + `expected_project_version`/`expected_report_version` + exact error/HTTP status); 2.8 precision conventions (integer cents half-up, 2dp bearing, 3dp settlement, 1dp rig hours, unrounded A-line); 2.9 the 10-category ordered evaluation pipeline; 2.10 derived rollups and cascades.
- §3 Business Logic (7 subsections, chronological lifecycle): client/project/plan revisions → rig scheduling/standing/clearance → drilling/refusal/offsets/authorization → sample custody/lab testing/USCS → foundation analysis → report sealing/issuance → observation/claims/closeout.
- §4 Endpoint table: 59 rows, 4 columns only (Method/Path/Description/Roles).
- §5 Error catalogue: 35 rows, 2 columns only (ID/HTTP status). No audit footer appended.

**Coverage audit (all PASS):**
- Contract 1 field coverage: 98/98 required identifiers in backticks (entity fields + endpoint inputs + query params + common fields), 0 missing.
- Contract 2 rule coverage: 64/64 state transitions expressed with preconditions + error IDs + side effects; 11/11 calculations in reconstructible prose (incl. scaffold's worked examples: 13,600-vs-13,599 pinned lab rounding, 500,000→490,000 discount tier, 4800-vs-6000 bearing variants, 40,000-vs-50,000 quantum variants); 33/33 validations mapped to error IDs; 3/3 OCC rules with write-endpoint + field + error + status; all 35 errors mentioned in §2/§3 prose; all enum/state strings present.
- Contract 3 §3 path purity: 704 backtick tokens scanned, 0 path/method violations.

**Scaffold ambiguities resolved (flagged, not invented):**
1. `ERR_PLAN_ALREADY_ACTIVE` vs. the SUPERSEDED cascade: the precondition forbids approving while another plan is APPROVED/LOCKED, yet the `supersedes_plan_id` cascade requires approving a revision while its predecessor is APPROVED. I rendered the supersede target as the natural exception to exclusivity so both rules remain reachable.
2. `FIELDWORK → LAB_ANALYSIS` requires every active-plan boring in {CLOSED, ABANDONED} — REFUSED borings do not satisfy it (REFUSED is terminal but absent from the gate). Transcribed exactly as scaffolded.
3. Derived-rollup recomputation (posture, exposure, invoice): scaffold does not state these bump `Project.version`, so the PRD claims `updated_at` refresh only and reserves Project version bumps for the three scaffold-declared events (lifecycle transitions, plan creation, authorization approve/revoke).
4. Offset authorization consumption: scaffold ties consumption to "beyond planned count" — rendered as: offsets up to `planned_boring_count` consume nothing; over-plan offsets require an APPROVED authorization with `consumed_boring_count < extra_boring_count`, increment it by 1, and exhaust it at equality.

## Step 5: Generate Unit Tests — 2026-08-13T07:45:00.000Z

All checks pass. Final summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/test_helpers/`):
- `types.py` — 15 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4), 18 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 59 PRD endpoints
- `api_errors.py` — `ApiErrorId` enum (34 IDs) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` helpers + tolerant `parse_instant` for timestamp comparisons
- `factories.py` — payload factories, input fields only
- `constants.py` — fee schedule, drilling tiers, bearing/settlement/quantum constants, clock defaults
- `test_users.py` — `TEST_USERS` for all 10 roles + `make_client_rep_headers` / `make_drilling_sub_headers` entity-backed builders (fixtures thread real entity ids through ownership-gated calls)
- `fixtures.py` — tiered composite chain (`setup_scoped_project` → `setup_fieldwork_project` → `setup_boring_cleared` → `setup_drilled_boring` → `setup_lab_received_sample` → `setup_accepted_uc_order` → `setup_verified_analysis` → … → `setup_construction_support_project`), plus claim/visit/authorization/offset helpers
- `__init__.py` — barrel export

**test_suite/** (10 files): `conftest.py` + 9 test files (`test_01` envelope/auth/intake through `test_09` claims/visits/posture), 75 test functions total. All compile and import cleanly; no skip/xfail markers; no scaffold references in comments.

## Instance translation

- **§1.8 Difficulty: 19/19 instances translated, 38 tests** (exactly 2 per instance).
- **§1.9 Corner: 37/37 non-stub instances translated, 37 tests.** All 5 `excluded_because:` stubs were verified to resolve to real §1.8 instances and were not translated.
- **Skipped: 0** — every non-stub instance passed the PRD-first two-condition filter.

Notable PRD-first adjudications (kept, with documented relaxations):
- `rejection_stales_analysis_blocks_issue` test 2 asserts issuance is blocked via `validate_error_is_one_of([ERR_ANALYSIS_DATA_STALE, ERR_ORDER_STATE_FORBIDS])` — after a rejection both category-5 guards fail simultaneously and the PRD does not rank them (error-precedence silence pattern).
- `project_computed_posture_input_ignored` asserts `posture == OPEN` on a plain create; the rogue-field variant was not exercised because rejecting unknown body fields is a PRD-consistent design choice (default-value/two-reader concern), noted in the docstring.
- `n60_average_excludes_non_drilled_borings` setup files a ticket for B-2 in addition to the recipe — the PRD's FIELD_AUTHORIZED gate ("Every Boring of the active plan has at least one UtilityClearance") requires it; the assertion is unaffected.

## Stage 2 self-check verdict (tag audit)

Programmatic audit confirmed: 75/75 test functions carry exactly one `Design:` line as the final docstring line; all 56 tags resolve to real instances in the source YAMLs; every difficulty instance has ≥2 tests and every non-stub corner instance ≥1; zero unknown/dangling tags; every quoted PRD citation survives whitespace-normalized literal grep of PRD.md (0 misses); stub cross-references all resolve. **Verdict: PASS.**

## Step 6: Generate Implementation — 2026-08-13T07:55:00.000Z

The implementation is complete and verified. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/workspace/implementation/`:

- `start.sh` — guarded launcher (`pip install` only if flask missing, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000, foreground)
- `requirements.txt` — flask
- `app.py` — Flask entry, blueprint registration, envelope-compliant error handlers
- `db.py` — in-memory store (dicts only, empty at boot, zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z` and never wall-clock, monotonic creation counter for stable `created_at` ordering
- `errors.py` — `ApiError` + full 35-entry error catalog
- `response.py` — exact envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, pagination fields in `meta` for lists
- `helpers.py` — auth middleware (X-User-ID/X-User-Role, 10 roles), typed body validators, limit/offset pagination (10/1/100, offset 0)
- `calc.py` — all calculations with `Decimal`/`ROUND_HALF_UP`
- `serialize.py` — per-entity wire shapes with rollups computed on read
- `routes_core.py`, `routes_field.py`, `routes_lab.py`, `routes_closeout.py` — the route surface

## Coverage

- **Endpoints: 59/59** (15 single GETs, 13 filtered list GETs, 30 mutations, `POST /geo/_clock/set_current_utc` returning 200 `{}`)
- **State machines: 13/13**, including cyclic loops (plan revise, report review loops, order rerun capped at 2, claim single appeal, VERIFIED→VERIFIED refresh) and system-only transitions (plan LOCKED/SUPERSEDED, sample CONSUMED, clearance EXPIRED sweep, auth EXHAUSTED, boring PLANNED→SCHEDULED)
- **Calculations: 11/11** — verified against the PRD's worked examples: 4800 provisional vs 6000 final psf; settlement 1.000 inclusive deep-foundation threshold; per-line lab rounding (2×6800=13600 not 13599); pre-discount tier (523000→520850; tier keyed on pre-discount gross); tiered drilling cost with rock multiplier on the deepest R feet + 45000 first-of-plan mobilization + 25000 floor; USCS tree incl. F==50.0 coarse boundary and unrounded A-line (tested SW/SM/SC/CL/ML/CH/MH); dual claim quanta (120000→40000/50000); committed rig hours; inclusive clearance expiry (valid at exactly `expires_on`, EXPIRED one second past via clock sweep); claims exposure rollup
- **Error catalog: 35/35** with correct HTTP codes, evaluated in the §2.9 pipeline order (auth 401 → role/ownership 403 → existence 404 → body 400 → state/OCC 409/412 → safety gates → constraints → temporal 422 → referential 422 → fiscal 422)

## PRD ambiguities resolved (interpretation chosen)

1. **`ERR_PLAN_ALREADY_ACTIVE` vs supersede cascade** — the plan named in `supersedes_plan_id` is exempted from the exclusivity check and is SUPERSEDED (if APPROVED) on approval, per the PRD's "natural exception" sentence.
2. **Report-issue guard ordering** — §2.9's category pipeline wins over §3.6's narrative order: OCC (412) is checked before segregation-of-duties (409, category 7).
3. **Project LAB_ANALYSIS→REPORT_REVIEW with a VERIFIED-but-STALE analysis** — returns `ERR_ANALYSIS_NOT_VERIFIED` (PRD §3.6 wording); `ERR_ANALYSIS_DATA_STALE` is reserved for the analysis-verify and report-issue endpoints per the scaffold's `applies_to`.
4. **Dangling body FKs** — nonexistent `client_id`/`subcontractor_id`/`supersedes_plan_id` → 400 `ERR_VALIDATION`; nonexistent `sample_id`/`observation_visit_id` → the dedicated 422 mismatch errors (they "fail to resolve" to the project).
5. **Drilling payload** — `actual_depth_ft` and `avg_n60` required (400 if absent); `rock_depth_ft` defaults 0, `groundwater_depth_ft` null.
6. **ClientRep/DrillingSub read scoping** — single GETs on another owner's entity → 403; lists are filtered to owned projects/assignments.
7. **All server timestamps from the logical clock** (created_at/updated_at/sealed_at/expires_on, 3-fractional-digit ISO); client-supplied datetimes (visit_date, window_start/end, issued_on, target_report_date) echoed as sent.
8. **`version` starts at 1**; rollup recomputation refreshes parent `updated_at` only — Project `version` bumps only on the three PRD-declared events (lifecycle transition, plan creation, authorization approve/revoke).
9. **REFUSED borings do not satisfy FIELDWORK→LAB_ANALYSIS** (gate requires {CLOSED, ABANDONED}), transcribed literally from the PRD.

Verified by four end-to-end suites (full engagement lifecycle, refusal→offset→authorization exhaustion, USCS variants, lab capacity=6, rerun cap, stale/refresh cascade, OCC precedence, error-pipeline precedence, empty-at-boot) — all pass, including a boot via `bash start.sh` on a fresh process.

## Step 7: Run Tests and Iterate — 2026-08-13T08:15:00.000Z

All 8 rounds: 75/75 passed, 0 failed, 0 errors. Clean sweep achieved.

## Summary

- **Iterations run**: 2 full 8-round parallel sweeps (plus one infrastructure-aborted sweep that wrote no results — the host is shared by many concurrent benchmark pipelines; rerun produced clean data).

- **Failing tests (union across rounds)**: 2, both in `TestRejectionStalesAnalysisBlocksIssue`, deterministic across all 8 rounds of sweep 1:
  - `test_rejection_resets_classification_and_stales_analysis`
  - `test_issuance_blocked_after_rejection`

- **Tests deleted**: none.

- **Diagnosis (per protocol)**:
  - STEP 1a/1b: The asserted rule is verbatim in PRD §3.4 ("Rejection cascades as a three-link chain: the sample's `uscs_class` resets to null (link 1); every `VERIFIED` FoundationAnalysis of the project goes `STALE` (link 2)... and report issuance is consequently blocked (link 3, §3.6)") and §3.6's issuance guards. Covered and uniquely derivable — tests kept at full strength.
  - STEP 2: TEST IS WRONG. The shared setup helper `_setup_with_rejected_errata_order` called `setup_pe_review_report()` (which walks the boring to `CLOSED`) and then issued `create_sample` against that CLOSED boring. PRD §3.4 states verbatim: "Sampling begins once a boring stands in `DRILLED` or `LOGGED` — logging a sample against a boring in any other state is rejected with `ERR_PROJECT_STATE_FORBIDS`." The implementation was PRD-faithful; the setup's request violated a PRD precondition.

- **Fixes applied to `test_suite/`**: `/home/ubuntu/github/CodingPRD/tasks/task_1419_geotechnical_engineering_subsurface/test_suite/test_07_reports_review_and_issuance.py` — restructured `_setup_with_rejected_errata_order` to build the second sample and its SIEVE_ANALYSIS/ATTERBERG orders-to-ACCEPTED (classification → `SC`) while the project still stands in `FIELDWORK` and the boring in `DRILLED`, then create/verify the analysis, walk the boring `LOGGED`→`CLOSED`, drive the project `LAB_ANALYSIS`→`REPORT_REVIEW`, advance the report to `PE_REVIEW`, and only then create the DIRECT_SHEAR errata order (expressly permitted during review) and reject it. Same assertions, same cascade coverage — the setup is now PRD-consistent.

- **Fixes applied to `test_helpers/`**: none needed (fixture chain tiers are individually PRD-faithful; the bug was in the test-local composition order).

- **Fixes applied to `implementation/`**: none — the implementation was correct.

- **Final state**: 75/75 passed in every one of the 8 concurrent rounds (600/600 test executions).

## Step 8: Finalize PRD — 2026-08-13T08:25:00.000Z

Step 8 complete. `workspace/PRD_FINALIZED.md` is written — a byte-identical copy of PRD.md, because the only `<step_7_diff>` item is a pure test-fixture bug that revealed no PRD silence and no PRD/impl mismatch.

## Summary

**Line counts / %-delta:** PRD.md 324 lines, PRD_FINALIZED.md 324 lines, 0% delta (diff clean, zero edits).

**Changes:** none. Per the HARD SCOPE, every PRD edit must trace to a step_7_diff fix that revealed PRD-silence or PRD-mismatch. The single fix (restructuring `_setup_with_rejected_errata_order` in `test_07_reports_review_and_issuance.py`) fixed test-local composition order only; the implementation was PRD-faithful and the PRD already pinned every rule involved verbatim. The minimal correct patch is the identity patch.

**Per-edit pre-edit search log** — zero edits were committed, so instead here is the verification record justifying the zero-edit outcome; for each subject the step_7 fix touches, the subagent enumerated and read every related impl path:

1. **Subject: sampling state gate** (the rule the old fixture violated). Paths enumerated: `create_sample` in `routes_field.py:423-460` — gate at lines 436-441 rejects borings not in `DRILLED`/`LOGGED` with `ERR_PROJECT_STATE_FORBIDS`; interval/recovery validation at 428-435, 442-447. PRD §3.4 (line 172) states the rule verbatim. Match — nothing to pin.
2. **Subject: lab-order project-state gate** (errata order during review). Paths enumerated: `create_lab_test_order` in `routes_lab.py:103-141` — gate at 113-118 permits `FIELDWORK`, `LAB_ANALYSIS`, `REPORT_REVIEW`; sample-project cross-check at 119-126; fee at creation via `calc.order_fee_cents`. PRD §3.4 (line 176) pins all of this, including "errata orders during review are expressly permitted". Match.
3. **Subject: rejection cascade (3-link chain)**. Paths enumerated: order transition in `routes_lab.py:164-230` — link 1 reset at 217-221, link 2 via `_stale_verified_analyses` at 72-77 (staleness of every `VERIFIED` analysis of the project on any order rejection, mirroring §3.5 line 190); link 3 via issuance guards. Also checked acceptance-side symmetric paths (`_recompute_uscs` at 80-97, destructive-consume at 207-216, rerun path at 187-197, 226-227). PRD §3.4 (line 180) pins the chain verbatim. Match.
4. **Subject: issuance guards**. Paths enumerated: `issue_report` in `routes_closeout.py:210-261` — all five PRD §3.6 guards present (`ERR_ANALYSIS_NOT_VERIFIED` 220-224, `ERR_ANALYSIS_DATA_STALE` 225-226, `ERR_ORDER_STATE_FORBIDS` 227-234, `ERR_STALE_REPORT_VERSION` 236-240, `ERR_SOD_PE_IS_PREPARER` 242-246), plus supersede-side-effect at 251-258. Impl surfaces `ERR_ANALYSIS_DATA_STALE` first after the errata rejection; the test accepts either that or `ERR_ORDER_STATE_FORBIDS`, and PRD §2.9 deliberately ranks only check categories, not errors within category 5 — that intra-category choice predates the step_7 fix, so it is out of scope for an edit. Match.
5. **Subject: classification → `SC`** (asserted mid-setup). Path: `calc.uscs_classify` in `calc.py:263-277` — F=42 ∈ (12, 50] with PI=12 > 7 yields `SC`, exactly the PRD §3.4 (line 182) decision tree. Match.
6. **Subject: analysis create/verify while project in `FIELDWORK`** (fixture order depends on it). Paths: create gate (PRD §3.5 line 186: `FIELDWORK`/`LAB_ANALYSIS`) and `foundation_analysis_transition` in `routes_lab.py:347-404` — verify guards at 365-372 are exactly the two PRD §3.5 (line 188) requirements (accepted UC order present, `data_status` `CURRENT`), with no extra project-state guard. Match.

No wording was inserted or revised anywhere, so the NO-NEW-MISMATCH rule is trivially satisfied. Step 9 inherits a PRD_FINALIZED.md identical to PRD.md.

## Step 9: Complete PRD — 2026-08-13T08:45:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

**Stats**
- Source: `PRD_FINALIZED.md` — 324 lines / 62,305 chars. `PRD_COMPLETED.md` — 324 lines / 65,061 chars. Char delta: **+2,756** (23 paragraphs touched, 0 sections added/removed).
- Counts: **22 ambiguity-pins, 2 mismatch-revisions** (24 edit hunks total).

**Changes** (all `impl/` paths under `workspace/`):

- §2.1 — insert — ambiguity — entity-backed roles get visibility scoping (not 403) on list endpoints: ClientRep sees only own projects/reports/claims/authorizations, DrillingSub only own rig assignments — `routes_core.py:183-184,559-560`, `routes_closeout.py:183-185,412-414,511-513`
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, or negative offset → `ERR_VALIDATION` 400; `created_at` ties broken by creation sequence — `helpers.py:153-190`
- §2.4 — revise — ambiguity — `version` starts at **1** on creation — `db.py:70`
- §2.9 (cat 4) — insert — ambiguity — non-object JSON body → `ERR_VALIDATION`; absent/unparseable body treated as empty object — `helpers.py:55-61`
- §2.9 (cat 5) — insert — ambiguity — on transition endpoints, (from,to) pair existence is checked before transition-specific payload validation (e.g. drilling measurements) — `routes_field.py:172-197`
- §3.1 — insert — ambiguity — `client_id` must reference an existing Client else `ERR_VALIDATION`; `base_fee_cents`/`additional_auth_cap_cents` are non-negative integers — `routes_core.py:132-140`
- §3.1 — revise — **mismatch** — `assumed_gwt_depth_ft` was "used in preliminary analysis"; impl consumes it nowhere, now pinned as recorded-for-reference-only — `routes_core.py:138,149`, `calc.py:194-198`
- §3.1 — insert — ambiguity — plan `planned_boring_count` non-negative integer, `planned_total_footage_ft` non-negative number; supplied `supersedes_plan_id` must reference a plan of the same project else `ERR_VALIDATION` — `routes_core.py:319-329`
- §3.1 — insert — ambiguity — boring `planned_depth_ft` strictly positive — `routes_field.py:122`
- §3.2 — revise — **mismatch** — `day_rate_cents`/`max_concurrent_rigs` were framed as rate/"ceiling" (implying enforcement); impl records both but no guard or calculation consumes them — `routes_core.py:435-436`, `calc.py:153-162`
- §3.2 — insert — ambiguity — rig-scheduling `subcontractor_id` must reference an existing Subcontractor else `ERR_VALIDATION` — `routes_core.py:494-496`
- §3.2 — insert — ambiguity — `valid_days` must be a positive integer when supplied — `routes_field.py:350`
- §3.3 — insert — ambiguity — drilling payload domains: `actual_depth_ft` required & strictly positive, `avg_n60` required & non-negative, `rock_depth_ft` optional non-negative (no cross-check vs `actual_depth_ft`), `groundwater_depth_ft` optional non-negative default null — `routes_field.py:185-189`
- §3.3 — insert — ambiguity — `refusal_depth_ft` additionally non-negative — `routes_field.py:191`
- §3.3 — insert — ambiguity — offset borings: strictly positive `planned_depth_ft`; when several APPROVED authorizations retain capacity, the earliest-created one is consumed — `routes_field.py:303,316-323`
- §3.3 — insert — ambiguity — authorization `authorized_amount_cents`/`extra_boring_count` are non-negative integers — `routes_closeout.py:475-476`
- §3.4 — insert — ambiguity — sample `depth_top_ft`/`depth_bottom_ft` non-negative — `routes_field.py:428-429`
- §3.4 — insert — ambiguity — a `sample_id` resolving to no existing sample fails as `ERR_SAMPLE_PROJECT_MISMATCH` (not 404/400) — `routes_lab.py:120-126`
- §3.4 — insert — ambiguity — USCS reclassification is skipped (class left unchanged) when the latest accepted sieve lacks `percent_passing_200` or the latest accepted Atterberg lacks `liquid_limit`/`plasticity_index` — `routes_lab.py:80-97`
- §3.5 — insert — ambiguity — `fs_required` (when supplied) and `footing_width_ft` strictly positive; `applied_bearing_psf` non-negative — `routes_lab.py:296-298`
- §3.5 — revise — ambiguity — `deep_foundation_required` compares the **rounded** (stored 3-decimal) settlement estimate against 1.0; when `n60_average` is zero, settlement/deep-flag are not recomputed — `calc.py:216-217`, `routes_lab.py:388-393`
- §3.6 — insert — ambiguity — DRAFT→TECH_REVIEW is role-checked only: any SeniorEngineer may submit, `prepared_by_user_id` is never compared — `routes_closeout.py:29,196-204`
- §3.7 — insert — ambiguity — findings filing actor pinned to StaffEngineer; `observed_bearing_psf` optional, non-negative when supplied, defaults null — `routes_closeout.py:38,328-329`
- §3.7 — insert — ambiguity — claim appeal (REBUTTED→UNDER_REVIEW) actor pinned to SeniorEngineer — `routes_closeout.py:48`

Everything else in the implementation (all 59 endpoints' role tables, every state machine transition and actor, all calculation formulas and constants, evaluation-order category placement, rollup definitions, clock sweep semantics, response envelope shapes) matched PRD-pinned behavior exactly and required no change.

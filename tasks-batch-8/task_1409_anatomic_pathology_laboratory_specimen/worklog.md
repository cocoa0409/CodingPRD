# Worklog — task_1409_anatomic_pathology_laboratory_specimen

## Step 1: Create Task Directory — 2026-08-13T04:09:00.000Z

Task directory `tasks/task_1409_anatomic_pathology_laboratory_specimen/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE (no index scan, no other directory touched).

## Step 3: Copy Shared Files — 2026-08-13T04:10:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1409_anatomic_pathology_laboratory_specimen/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-13T05:08:00.000Z

All three artifacts are complete and verified. Final state:

## Summary

Generated a fresh scaffold for `task_1409_anatomic_pathology_laboratory_specimen` purely from the scenario text plus the skill spec (no sibling tasks consulted).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): 13 entities, 10 state machines, 2 OCC concurrency rules, 8 calculations, 57 ordered validations, 69 endpoints (incl. `POST /pathology/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z startup default), 57 error codes, 4 roles (Pathologist is `entity_backed:Pathologist`; LabAdmin/Histotech/PathologyAssistant opaque; segregation-of-duties on consultations and amendments).
- `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with 18 instances (all 9 rules × 2, all differentiation clauses honored).
- `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` with 71 instances across all 9 guide sections (64 full recipes + 7 `excluded_because` stubs, all resolving to real §1.8 instances).

**Key design decisions (harder-than-expert target):**
- Cyclic state machines: Case FINAL↔AMENDING amendment loop, Slide QC-fail→recut loop, Consultation decline/expire→reroute loop.
- Dual-variant calcs on different domains: TAT deadline CALENDAR vs BUSINESS_HOURS (Case), discrepancy rate simple vs severity-weighted (Pathologist).
- Combinatorial formulas in two modes: tiered complexity classification (4 inputs, inclusive-lower boundaries) and per-event tissue rounding (pinned round-then-sum: 3.33/3.33/3.34 → 90.1, not 90.0).
- Depth-4 transitive cascade (stain result → reflex child order → complexity class → deadline → breach re-eval) plus tissue-depletion cascade.
- Two distinct validation-priority conflicts (state vs business_safety at sign-out; business_safety vs business_temporal at release approval).
- Interval rules with genuinely different semantics: half-open adjacency-allowed coverage windows vs closed touching-conflicts loan intervals vs 60-minute buffered unavailability windows.
- Compensating invariants: exactly-one-SIGNED-report per FINAL case; workload-score conservation across assign/reassign.
- All formula-derived asserts pre-computed by code (deadlines 2026-08-09T16:00 vs 2026-08-17T10:00, tissue 90.1/4.0, scores 8.5/10.5, rates 1.0/2.0, retention 2026-08-19T14:30, breach 60 min, etc.).

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (69 endpoints, 13 entities, 18 §1.8 + 64 §1.9 instances, 917 calls scanned). Additional scripted checks passed: no forbidden concurrency vocabulary, every error code referenced by a validation and vice versa, 89 globally unique instance names, enum closure, and correct file split.

## Step 4: Generate PRD — 2026-08-13T05:30:00.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/workspace/PRD.md`.

**Structure**: Introduction (3 paragraphs from the lab-operations angle), §2 with 9 domain-derived subsections (RBAC, verbatim response structure, pagination + list filters, common properties/accession numbers, logical clock & sweeps, case-anchored cascading reconciliation, precision/rounding discipline, OCC, validation order), §3 with 8 lifecycle subsections (intake/TAT, accessioning-to-disposal, block/slide tissue accounting, stains & reflex, assignment/coverage/workload, sign-out/amendment/discrepancy, consultations, release loans), §4 endpoint table (4 columns, 68 endpoints), §5 error catalogue (2 columns, 57 errors).

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body: 69 required, 69 present, 0 missing
- endpoints[].query_params: covered (filter names enumerated in §2.3), 0 missing
- endpoints[].path_params: {id} covered, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: global funnel (priorities 1–5) plus the three emphasized orderings (safety-before-temporal on release approve, self-before-assigned on consult, tissue-budget-last on section/recut) and the EMPTY_SLIDE_SET/SLIDES_NOT_READY mutual-exclusion note all expressed in §2.9/§3 prose
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_case_version/expected_reflex_rule_version + ERR_STALE_CASE_VERSION/ERR_STALE_VERSION + HTTP 412 all named in §2.8)
- state_machines[].transitions: all Specimen/Case/Block/Slide/StainOrder/Report/Consultation/Discrepancy/ReleaseRequest/CoverageWindow transitions expressed with preconditions, error IDs, and side-effect cascades
- calculations[]: 8 checked, 8 fully expressed in prose (cold ischemia truncation, TAT hours 48/72/120/168 with CALENDAR vs BUSINESS_HOURS advance-then-consume, complexity weights 1/2/3/0 + 1.0/0.5/2.0 with tier bounds 4.0/10.0/20.0, workload 1/2/3/5 + consult weight 2, per-event round-half-up tissue accounting with the 3.33/3.33/3.34 → 90.1 pinning example, 365-day discrepancy rates with severity weights 1/3/5 and 4-decimal rounding, strict-greater breach rule, reflex fire order/dedupe/depth-3 guard)
- validations[] conditions: all 57 rules matchable to their error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed, including the case-cancel two-variant cascade (OPEN vs WORKUP), sign-out atomic cascade, and clock sweeps
- entities[].fields[] structured content: defaults, null-until semantics, computed-field definitions all reconstructible from prose
- sibling-branch symmetry: amend/sign vs amend/cancel, QC PASS vs FAIL, resolve-from-OPEN (LEVEL_1) vs resolve-from-ACKNOWLEDGED rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 626
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to the canonical `section-2.2-response-structure.md`. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T06:10:00.000Z

Generation complete. Summary of what was built and key adjudication decisions:

## Generated output

**`test_helpers/` (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/test_helpers/`:
- `types.py` — 13 entity TypedDicts + 18 status/type enums; all entities carry `common_fields: true` so all include `id`/`created_at`/`updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 50 endpoints incl. `set_clock`).
- `api_errors.py` — `ApiErrorId` (57 codes) + HTTP status map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity shape assertions plus `parse_instant`/`assert_instant_equal` (format-tolerant timestamp comparison, since the PRD pins second-precision for computed datetimes but 3-fractional-digit format for `created_at`).
- `factories.py`, `constants.py` (TAT hours, tier bounds 4.0/10.0/20.0, weights, cold-ischemia limits 60/90, `MAX_REFLEX_CHAIN_DEPTH=3`, 60-min buffer — all PRD-stated), `test_users.py` (opaque roles as shared constants; `make_pathologist_headers(user_id)` mandatory builder for the entity-backed Pathologist role).
- `fixtures.py` — tiered composites: `setup_workup_case`, `setup_qc_passed_case`, `setup_pending_signout_case`, `setup_final_case`, `setup_consulted_case`, plus per-step helpers threading entity ids into pathologist headers.

**`test_suite/` (11 files, 100 tests)** — 36 difficulty-queue tests (18 instances × 2) + 64 corner-queue tests (every non-stub instance × 1). Audits all pass:
- **Coverage**: every §1.8 instance has ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`; every non-stub §1.9 instance has ≥1 tagged `Design: Corner/<section>/<name>`; all 7 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated; no phantom tags.
- **Citations**: 170 quoted PRD sentences all survive whitespace-normalized verbatim match against `PRD.md` (4 initial failures — elisions and endpoint-titular table rows — were rewritten to rule-bearing prose and rechecked).
- No `skip`/`skipif`/`xfail`, no scaffold references, all files compile, `pytest --collect-only` collects 100 tests cleanly.

## Key PRD-first adjudications
- **`retention_disposal_inclusive_boundary`**: the PRD never states `RETENTION_DAYS` values, so the absolute `retention_until` is not derivable. Tests read `retention_until` from the completed specimen at runtime, then drive the logical clock to `retention_until − 1s` (expects `ERR_RETENTION_NOT_ELAPSED`) and to exactly `retention_until` (expects success, `wet_tissue_disposed_at == retention_until`) — the inclusive-boundary rule itself is PRD-verbatim.
- **`submit_from_open_and_amend_sign_without_amendment_rejected`**: the amend/sign-on-FINAL half is genuinely ambiguous in the PRD (§2.9 funnel puts ownership checks at priority 2 before state rules, but amender is null on a FINAL case while §3.6 names `ERR_CASE_NOT_AMENDING` as the case-state guard). Translated with `validate_error_is_one_of([ERR_CASE_NOT_AMENDING, ERR_FORBIDDEN])`; the submit-from-OPEN half asserts `ERR_CASE_NOT_IN_WORKUP` exactly.
- **Priority-ordering tests kept only where PRD-derivable**: the §2.9 funnel enumeration ("state, safety, constraint, referential, temporal, and tissue-budget rules then follow in their declared order") plus the three explicitly emphasized orderings cover the sign-out state-vs-safety pair, the release safety-vs-temporal pair, existence-before-state, and budget-last — all were judged uniquely derivable and kept.
- Bug caught in self-review: the two-variant TAT test originally created the same MRN twice in one test (would 409); parameterized the fixture MRN.

## Step 6: Generate Implementation — 2026-08-13T06:40:00.000Z

All functional work is validated. The 3 errors are `pytest-timeout` during setup — the per-test server restart exceeded the 10s window because other benchmark sessions are running concurrent sweeps on this shared box (load avg 13); the previous run on the same code had 99/100 with zero errors. The single consistent failure is a test-suite bug.

## Report

**Delivered**: complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/workspace/implementation/`:

- `start.sh` — executable, guarded install (`python3 -c "import flask"` check before pip), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask wiring, envelope-shaped 404/405/exception handlers, global store lock per request (OCC race safety)
- `db.py` — in-memory store, empty on every boot (no seeding), logical clock starting at exactly `2026-08-01T00:00:00Z`
- `errors.py`, `helpers.py` — ApiError with scaffold error_ids; envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists); X-User-ID/X-User-Role auth; shape validators; ISO-8601 parsing; per-event `Decimal` ROUND_HALF_UP helpers
- `calc.py` — all calculations (business-hours TAT, tiered complexity, workload, 365-day discrepancy rates, per-event tissue accounting, reflex evaluation with once-per-case dedupe and depth-3 guard), cascades, clock sweep, and serializers
- `routes_admin.py` / `routes_cases.py` / `routes_lab.py` / `routes_review.py` — all 69 routes from the endpoint table, verified registered

**Key spec-fidelity decisions** (all traced to PRD/corner-design pins): validation funnel auth→role→shape→existence→state→business with the documented overrides (release safety before temporal, self-consult before is-assigned, tissue budget last, readiness before empty-set on submit); ownership checks apply only when the relevant FK is set (so amend/sign on a FINAL case yields `ERR_CASE_NOT_AMENDING` while a wrong-caller on an AMENDING case yields 403); reject checks `ERR_BLOCKS_EXIST` before `ERR_SPECIMEN_NOT_ACCESSIONED` (corner design pins this for a PROCESSING specimen); slides expose `on_loan` (the release test reads it even though the scaffold's Slide entity omits it); dashed UUIDs for entity ids; second-precision format for computed/event timestamps vs 3-fractional-digit `created_at`/`updated_at`; `RETENTION_DAYS` = 14 for all specimen types (only BIOPSY=14 is pinned anywhere).

**Verification**: 270 standalone scenario checks (covering every difficulty-design and corner-design recipe) all pass. Official harness `prd-bench-local-run --isolation per-test-server` (start command `cd <abs impl dir> && bash start.sh` — the runner requires this form to absolutize restart paths): **99/100 passed**. The one failure, `test_level1_discrepancy_resolves_directly_from_open`, is a test-suite bug — `test_08_amendments_and_discrepancies.py` line 343 calls `setup_workup_case` without importing it (`NameError`); my equivalent standalone check of that exact behavior (LEVEL_1 resolves from OPEN, `resolved_at` = logical clock, `resolved_with_amendment` false) passes. A stability re-run under heavy shared-box contention showed 3 additional setup-time `pytest-timeout` errors (server restart polling exceeded 10s under load from other sessions' concurrent sweeps) on tests that pass cleanly otherwise.

## Step 7: Run Tests and Iterate — 2026-08-13T07:00:00.000Z

Verified independently: all 8 rounds completed with passed=100, failed=0, total=100. The sweep is clean — the single known failure is resolved and no flakiness surfaced across the 8 concurrent rounds.

## Summary

- **Iterations run:** 1 (one 8-round parallel sweep after the initial fix; all 8 rounds green, so no further iterations needed).

- **Tests deleted:** None. The only failing test traced to verbatim PRD coverage and was retained.

- **Fixes applied to `test_helpers/`:** None. `setup_workup_case` was already correctly defined in `test_helpers/fixtures.py` (line 524) and exported via the wildcard import in `test_helpers/__init__.py`.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/test_suite/test_08_amendments_and_discrepancies.py` — `test_level1_discrepancy_resolves_directly_from_open` (line 343) called `setup_workup_case` without importing it (NameError). Added `setup_workup_case` to the `from test_helpers import (...)` list. Verified PRD coverage before fixing: PRD §3.6 (line 188) verbatim states "Resolution is severity-tiered: a `LEVEL_1` discrepancy may be resolved directly from `OPEN` with `resolved_with_amendment` false permitted" and "Resolution stamps `resolved_at` and records `resolved_with_amendment`"; PRD §2.5 (line 92) states "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`". The test is fully PRD-faithful; only the import was missing. Also proactively AST-scanned all other test files for the same used-but-not-imported bug class — none found.

- **Fixes applied to `implementation/`:** None. Reviewed the discrepancy-resolve logic in `routes_review.py` (severity-tiered state gate, amendment requirement for LEVEL_2/3) — it already matches PRD §3.6 exactly.

**Final state:** 100/100 passing in each of the 8 parallel rounds (800/800 total test executions), zero flaky failures observed. No boot-timeout infrastructure noise occurred during this sweep.

## Step 8: Finalize PRD — 2026-08-13T07:05:00.000Z

Verification complete. The Step 7 diff contains exactly one change — a test-suite import fix (`setup_workup_case` added to the `from test_helpers import (...)` list in `test_08_amendments_and_discrepancies.py`) — which is a pure fixture bug (NameError from a missing import), not a behavioral choice. It reveals no PRD silence and no PRD/implementation mismatch:

- The behavior the test exercises (LEVEL_1 discrepancy resolved directly from `OPEN`, `resolved_with_amendment` false permitted, resolution stamping `resolved_at`/`resolved_with_amendment`) is verbatim-pinned by PRD §3.6 (line 188), and the implementation in `implementation/routes_review.py:254-293` matches that prose exactly (severity-tiered state gate at lines 265-273, LEVEL_2/3 amendment requirement at lines 274-288, stamping at lines 289-291).
- The clock startup value the fixture relies on is verbatim-pinned by PRD §2.5 (line 92: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`").
- No implementation changes, no test_helpers changes, no test deletions.

Per the run note, zero PRD edits is the expected outcome, and I confirm it: `PRD_FINALIZED.md` is a verbatim copy of `PRD.md`.

## Summary

**Line counts:** PRD.md = 344 lines; PRD_FINALIZED.md = 344 lines; delta = 0 (0.0%). `diff` confirms the files are byte-identical.

**Changes:** 0

- No edits were made. The sole Step 7 item was a test-suite import fix (missing `setup_workup_case` import in `test_suite/test_08_amendments_and_discrepancies.py:343`) — a pure fixture bug with no behavioral content. The behavior it touches is already fully and verbatim determined by PRD §3.6 line 188 and §2.5 line 92, and the implementation (`implementation/routes_review.py:254-293`) matches the PRD exactly. No PRD silence or mismatch to patch.

**Per-edit pre-edit search log:** No edits were committed, so no searches were triggered. As due diligence for the zero-edit decision I read PRD §2.5-§3.7 (`PRD.md:80-199`) and the discrepancy acknowledge/resolve implementation (`routes_review.py:237-293`) to confirm the Step 7 site's behavior is already PRD-determined and that nothing in the diff narrative implies a concrete behavioral choice left open by the PRD.

## Step 9: Complete PRD — 2026-08-13T07:15:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1409_anatomic_pathology_laboratory_specimen/workspace/PRD_COMPLETED.md`.

## Summary

**Source**: `PRD_FINALIZED.md` (identical to PRD.md). Line counts: 344 → 346 (+2 lines); char delta: 58,443 → 61,712 (+3,269 chars).

**Counts**: 22 ambiguity-pins, 3 mismatch-revisions (25 inline edits total; no new sections, no behavior invented).

**Changes** (section — insert/revise — class — what changed — impl ref):

- §2.1 — revise — **mismatch** — assignee-based ownership checks (submit-for-signout, sign-out, discrepancy acknowledge) apply only when `assigned_pathologist_id` is recorded; a null assignee passes for any Pathologist — routes_cases.py:170-172, 202-204; routes_review.py:243-245
- §2.2 — insert — ambiguity — unmatched routes and unsupported methods return `ERR_NOT_FOUND` (404) in the standard error envelope — app.py:43-51
- §2.3 — revise — ambiguity — `limit`/`offset` are clamped into range (not rejected), non-integer values are `ERR_INVALID_REQUEST`, `created_at` ties break by insertion order, `has_more` = (offset+limit < total_count) — helpers.py:240-265
- §2.4 — revise — ambiguity — accession-number year/sequence derive from the logical clock's calendar year — routes_cases.py:360-363
- §2.5 — revise — ambiguity — clock-set returns `200` with `data.current_utc`; all server timestamps (`created_at`, `updated_at`, event stamps, `api_request_timestamp`) read the logical clock — routes_admin.py:295-304; helpers.py:85-93
- §2.7 — revise — ambiguity — all resource datetime fields are second-precision except `created_at`/`updated_at`/`api_request_timestamp` (3 fractional digits) — helpers.py:24-38; calc.py serializers
- §3.2 — revise — ambiguity — two-identifier check precedes the received/collection temporal check; accession increments the parent case `version` by 1 — routes_cases.py:351-358, 382
- §3.2 — revise — **mismatch** — grossing guard is "case not CANCELLED/FINAL" (terminal guard, evaluated first), not "case in OPEN or WORKUP"; rejection's blocks-exist check fires before the ACCESSIONED-status check — routes_lab.py:91-94, 113-122
- §3.2 — revise — ambiguity — retention period pinned to 14 days for every specimen_type — calc.py:20, 336-341
- §3.3 — revise — ambiguity — `ERR_GROSS_NOT_RECORDED` covers any non-GROSSING/PROCESSING specimen status (ACCESSIONED, REJECTED, COMPLETE) — routes_lab.py:161-163
- §3.3 — revise — ambiguity — block-state check (NOT_EMBEDDED/DEPLETED) precedes label-uniqueness and slide-state checks on slide create/section/recut — routes_lab.py:233, 250-257, 315, 379
- §3.3 — revise — ambiguity — QC-review `reason` is optional (null when omitted); recut retains the recorded `qc_failure_reason` — routes_lab.py:344-357, 260-273
- §3.4 — revise — ambiguity — stain-order checks fire in order case-state → cold-ischemia → block-ownership; creating an order increments case `version` by 1 — routes_cases.py:400-413, 427
- §3.4 — revise — ambiguity — reflex-rule firing residual ties (identical created_at) break by creation order — calc.py:357
- §3.4 — revise — ambiguity — reflex-rule update is partial (omitted fields kept), followup≠trigger invariant evaluated on merged values, stale-version check before duplicate-triple check — routes_admin.py:221-277
- §3.5 — revise — ambiguity — selector residual ties break by registration order — calc.py:280-288
- §3.5 — revise — ambiguity — reassignment always requires an explicit `pathologist_id` (no server selector) — routes_cases.py:145
- §3.6 — revise — **mismatch** — submit-for-signout ownership check conditional on a recorded assignee — routes_cases.py:170-172
- §3.6 — revise — ambiguity — sign-out returns the updated case; amend returns the draft report (201); amend/sign returns the newly signed report; amend/cancel returns the updated case — routes_cases.py:215, 257, 295, 309
- §3.6 — revise — ambiguity — manual discrepancy creation increments case `version` by 1; consultation-created discrepancies do not — routes_cases.py:521; routes_review.py:132-152
- §3.7 — revise — ambiguity — accepting when the clock equals `due_at` exactly is rejected with `ERR_CONSULTATION_WRONG_STATE` (409) — routes_review.py:81-84
- §3.7 — revise — ambiguity — decline `reason` is optional (null when omitted) — routes_review.py:97-100
- §3.7 — revise — ambiguity — reroute payload carries only `consultant_pathologist_id` and `due_at`; `subspecialty`/`question_text` are unchanged — routes_review.py:176-207

All other PRD statements (error catalogue, endpoint table and roles, state machines, tissue accounting with per-event rounding, complexity/TAT formulas, reflex depth/once-per-case guards, SoD rules, release gates and ordering, OCC scope, validation precedence examples) were verified against the implementation and already matched uniquely.

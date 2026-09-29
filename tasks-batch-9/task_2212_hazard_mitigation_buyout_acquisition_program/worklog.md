# Worklog — task_2212_hazard_mitigation_buyout_acquisition_program

## Step 1: Create task directory — 2026-09-01T01:56:01.691Z

Created `tasks/task_2212_hazard_mitigation_buyout_acquisition_program/` and `tasks/task_2212_hazard_mitigation_buyout_acquisition_program/workspace/` (directory name pre-allocated by the invoking command; no index scan performed).

## Resume — 2026-09-01T02:35:00.000Z

Resumed after crash. Disk audit: only `worklog.md` and empty `workspace/` present. SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/INSTRUCTION.md, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md all MISSING. Pipeline restarts at Step 2.

## Step 3: Copy shared files — 2026-09-01T02:35:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2212_hazard_mitigation_buyout_acquisition_program/workspace/INSTRUCTION.md` (53 lines).

## Resume — 2026-09-01T03:44:16.137Z

Second resume after crash. Disk audit:
- `worklog.md` — present.
- `workspace/INSTRUCTION.md` — VALID (53 lines, byte-identical to project-root `INSTRUCTION.md`). Step 3 complete.
- `SCAFFOLD.yaml` — **TRUNCATED** (1208 lines, parses as YAML but contains only `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities` (14), `state_machines` (5 of 8 planned); §1.4 calculations, §1.5 validations, §1.6 endpoints, §1.7 errors/roles all absent; file ends mid-`state_machines`). Treated as MISSING.
- `_scaffold_plan.md` — scratch plan left by the crashed scaffold-generator run (not a pipeline artifact).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md` — MISSING.

Pipeline restarts at Step 2 (scaffold regeneration), then continues Step 4 → Step 9. Step 3 not redone.

## Step 2: Generate scaffold — 2026-09-01T05:33:40.000Z

All three scaffold artifacts are complete, parse cleanly, and pass `scaffold_lint.py`. `_scaffold_plan.md` has been deleted.

## Files written
- `SCAFFOLD.yaml` (4257 lines) — top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, global_constants, validations, endpoints, errors, roles`. No `scaffold_difficulty_design` / `scaffold_corner_design` keys (file split honored).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2796 lines) — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4338 lines) — single top-level key `scaffold_corner_design`.

## Counts
| Item | Count |
|---|---|
| §1.1 entities | 15 |
| §1.2 state machines | 12 |
| §1.3 concurrency rules | 2 |
| §1.4 calculations | 13 |
| §1.4b global constants | 21 |
| §1.5 validations | 71 |
| §1.6 endpoints | 73 |
| §1.7 errors | 71 |
| §1.7 roles | 6 |
| §1.8 rules / instances | 9 / 25 (min 2 per rule) |
| §1.9 sections / instances | 9 / 63 (44 with `test_recipe`, 19 `excluded_because` stubs) |

§1.9 sections, in claim-extraction-guide order: entities (10), state_machines (19), calculations (8), validations (8), endpoints (7), errors (1), rbac (4), cross_cutting_complexity_layers (5), consistency_model (1).

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     15
  §1.8 instances scanned:     25
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  1100

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage-audit notes
- **Error coverage:** all 71 `error_id`s are asserted somewhere across the union of §1.8 + §1.9. 0 unreferenced.
- **Grounds resolvability:** 343 `grounds:` references all resolve to real SCAFFOLD.yaml paths (9 dangling refs found and fixed earlier, incl. `global_constants.DOB_SOURCE_FACTORS` → `calculations.dob_deduction_total.constants.DOB_SOURCE_FACTORS` and `concurrency_rules.program_income_stale_project` → `…program-income-stale-project`).
- **Name uniqueness:** 25 + 63 = 88 instance names, 0 duplicates across the two design files.
- **`excluded_because` discipline:** all 19 stubs cite a `difficulty_instance` that exists by name in SCAFFOLD_DIFFICULTY_DESIGN.yaml, and none carries a `test_recipe`. All 44 non-stub instances have a `test_recipe`.
- **Forbidden concurrency vocabulary:** 0 hits for all nine banned phrases across all three files (two "simultaneously" occurrences were rewritten to "in the same write"). OCC on parent `version` → 412 is the only concurrency mechanism used.
- **Assert field-name audit (final fixes this session):** every `Entity.${var}.field` reference in every `assert:` line was checked against the §1.1 field sets (with `common_fields: false` still supplying `id` + `created_at` per SKILL.md L263). Six defects fixed in SCAFFOLD_CORNER_DESIGN.yaml: `PurchaseOffer.gross_offer_cents` → `base_value_cents` (×3) and removal of three nonexistent `MitigationProject.program_income_cents` clauses (the real field is `program_income_balance_cents`). One fix also corrected arithmetic — the xref instance asserted `net_offer_cents == 20000000` for an OWNER_OCCUPIED parcel with dob 0, which per `net_offer_amount` must be `pre_incentive_net 20000000` at the 0.07 tier → `incentive_cents 1400000`, `net_offer_cents 21400000`. Re-audit is CLEAN.
- **Earlier structural note:** the P66 (`ERR_APPEAL_LIMIT_REACHED`) recipe was rewritten once reachability analysis showed the limit is only hit via the `CLAIM_SUBMITTED → CLAIM_DENIED → APPEALED` cycle (not `APPEALED → CLAIM_DENIED_FINAL`), yielding a 10-call cycle ending at `appeal_count == 2`.
- **Lint-shape precaution:** no `call:` string contains a query string (e.g. `GET /deed-restrictions` with `payload: {parcel_id: …}`), since lint check (a) parses the raw path.

## Step 4: Generate PRD — 2026-09-01T05:59:30.000Z

PRD generation for task 2212 is complete.

## Output
`workspace/PRD.md` — **667 lines**, written incrementally across ~14 append operations, verified complete on disk (ends at the last `## 5` table row, no truncation, no TODO/TBD/placeholder text, no audit footer inside the document).

## Section list
- `# Hazard Mitigation Buyout Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC (6 roles, entity-backed `SubrecipientCoordinator`), 2.2 API Response Structure (pasted verbatim), 2.3 Pagination and List Ordering, 2.4 Resource Identity/Audit Timestamps/Versioning, 2.5 The Logical Program Clock, 2.6 Money/Measurement/Rounding Discipline, 2.7 Stale-Read Protection, 2.8 Path Resolution/Cascades/Derived-Total Reconciliation, 2.9 Rejection Precedence (11 bands, all 71 error IDs in ascending priority + the 3 conflict pairs), 2.10 Segregation of Duties (SoD-1/2/3)
- `## 3. Business Logic & Workflows` — 3.1 Project/BCA/Award, 3.2 Parcel Inventory/Adjacency/Pre-Event Value, 3.3 Voluntary Participation/Holdouts/Viability, 3.4 Appraisal & Independent Review, 3.5 DOB/Offer Development/Federal Obligation, 3.6 Relocation Assistance, 3.7 Closing/Demolition/Utilities/Debris, 3.8 Perpetual Open-Space Restriction & Monitoring, 3.9 Program Income & Closeout
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Coverage audit
- **Endpoints: 73/73.** Every declared `method | path` pair appears as a literal row in §4 (programmatic diff against the scaffold's `endpoints:` block — zero missing).
- **Errors: 71/71.** All rows present, in exact `priority:` order, each HTTP status cross-checked against the scaffold's `validations` block — zero mismatches. (The scaffold's `ERR_XXX` is a template comment token, not a real error.)
- **Calculations: 13/13** rendered as prose with no pseudocode: `benefit_cost_ratio` (3.1), `neighborhood_viability_ratio` (3.3), `appraisal_validity_window` (3.4), `dob_deduction_total` + `net_offer_amount` + `federal_obligation` (3.5), `replacement_housing_payment` + `rental_assistance_payment` (3.6), `demolition_buffered_window` + `debris_diversion_pct` (3.7), `monitoring_schedule` + `protected_open_space_acres` (3.8), `program_income_federal_share` (3.9).
- **State machines: 12/12** (72 transitions), including both parallel `Parcel` dimensions, the `UtilityDisconnection` `FAILED` self-loop and `CONFIRMED → FAILED` bubble-up, and the cyclic `DeedRestriction` lifecycle.

## Hard Contract results
1. **Field-Name Coverage — PASS.** All 182 required identifiers (154 entity fields ∪ 124 endpoint input/query/path identifiers) appear verbatim in backticks; diff returned 0 missing. The 15 path-parameter identifiers plus `deed_restriction_id` were secured by a dedicated §2.8 paragraph enumerating them.
2. **Rule Coverage — PASS.** All transitions, preconditions, side effects, cross-entity cascades (three depth-3 chains), `applies_to` scopes, OCC rules, field types/defaults/initial values, and sibling-branch symmetry (e.g. all three `terminate` from-states, all five `resolve` edges, both work-order start from-states) are stated.
3. **§3 Path Purity — PASS.** No backticked token anywhere in §3 starts with `/`, is a bare HTTP method, or combines method+path (0 violations).

## Zero-Silence Rule notes (precondition declared, no dedicated error → attributed error)
- Project submit's "≥1 SUBMITTED BCA" and "≥1 parcel" → `ERR_INVALID_PROJECT_STATE`
- "No other BCA already VALIDATED" → `ERR_INVALID_BCA_STATE`
- Future-dated `voluntary_acknowledgement_signed_on` → `ERR_INVALID_REQUEST`
- Parcel not `VALUE_ESTABLISHED` at offer presentation → `ERR_INVALID_OFFER_STATE`
- Parcel not `OFFER_ACCEPTED` at closing fund → `ERR_INVALID_CLOSING_STATE`
- Duplicate contractor `name` → `ERR_INVALID_REQUEST`
- Closeout INITIATE's all-parcels-settled, no-`VIOLATION_OPEN`, and `participating_parcel_count >= 1` → `ERR_INVALID_PROJECT_STATE`
- `prohibited_use_code` must be a member of `prohibited_uses` → `ERR_INVALID_REQUEST`

## Scaffold inconsistencies resolved (implementer-visible choices)
- `participating_parcel_count`: entity field's 4-status set chosen over the viability calc's 3-status set (corroborated by the transitions' recompute lists).
- `cost_share_federal_pct`: entity constraint `0.5–1.0` chosen over validation 4's "(0, 1]"; §2.9 worded neutrally as "outside the permitted band".
- Work-order start: endpoint's "parcel `acquisition_status` is not checked here" chosen over the `READY → IN_PROGRESS` precondition; noted that the `CLOSED → DEMOLISHED` cascade only fires if the parcel actually reached `CLOSED`.
- Asbestos/certification gate rendered uniformly for both `READY` and `FAILED_INSPECTION` starts (validation 36 scopes it to the endpoint).
- §2.9 conflict-pair numbering follows the authoritative `priority:` keys (28/36/46/55), not the stale header comment (26/34/44/53).

## Step 5: Generate unit tests — 2026-09-01T07:22:00.000Z

The suite is complete. Summary:

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_2212_hazard_mitigation_buyout_acquisition_program/`

**Stage 1 — `test_helpers/` (2,798 lines)**
`types.py` 554, `api_client.py` 338, `api_errors.py` 160, `assertions.py` 401, `constants.py` 86, `factories.py` 362, `fixtures.py` 694, `test_users.py` 72, `__init__.py` 131.

**Stage 2 — `test_suite/` (7,212 lines, 116 tests)**
Queue A (53 tests): `conftest.py` 73, `test_01_dual_variant_calculations.py` 212, `test_02_combinatorial_formulas.py` 289, `test_03_non_linear_state_machines.py` 354, `test_04_transitive_cascades.py` 203, `test_05_rejection_precedence.py` 287, `test_06_boundary_precision.py` 330, `test_07_cross_entity_state_dependency.py` 319, `test_08_temporal_overlap.py` 361, `test_09_compensating_invariants.py` 362.
Queue B (63 tests): `test_10_corner_entities.py` 518, `test_11_corner_state_machines.py` 342, `test_12_corner_state_machine_ordering.py` 428, `test_13_corner_state_machine_limits.py` 692, `test_14_corner_calculations.py` 274, `test_15_corner_validations.py` 441, `test_16_corner_endpoints.py` 364, `test_17_corner_endpoint_guards.py` 192, `test_18_corner_closeout_gauntlet.py` 309, `test_19_corner_errors.py` 191, `test_20_corner_rbac.py` 385, `test_21_corner_concurrency_and_consistency.py` 286.

## Coverage audit

- **Queue A (§1.8): 25/25 non-stub instances translated** → 53 tests.
- **Queue B (§1.9): 44/44 non-stub instances translated** → 63 tests (19 stub/`excluded_because` instances correctly untranslated).
- **Zero instances skipped.** Every non-stub instance passed the PRD-first two-condition filter.
- Tag audit: 116 tests, 116 `Design:` lines, exactly one per test and always the last docstring line; no tag points at a non-existent or stub instance.
- `python3 -m compileall` clean over both directories; no generated file contains the word "scaffold".

## Design-vs-PRD deviations applied (remedy patterns, never weakening)

**Assertions omitted/corrected (pattern 1):**
- Difficulty instances 7, 17 (×2), 21 — unsupported assertions omitted.
- Corner `calculations` 1 — `validity_end_date` asserted after submission (PRD computes it there, not at creation); Corner `calculations` 3 — three post-DECLINE denominator-shrink assertions dropped (PRD counts `DECLINED` inside `participating_parcel_count`).
- Corner `validations` 4 — dropped `acquisition_price_cents == 21400000` (incentive is 0 on TENANT_OCCUPIED).
- Corner `endpoints` clock instance — `created_at == "2027-03-15T12:00:00Z"` relaxed to `.startswith(...)` because PRD §2.4 mandates three fractional digits.
- Corner `endpoints` 2 — `federal_obligated_cents` corrected 15,000,000 → **16,050,000** (design slip).
- Corner `errors` — corrected to 20,000,000/15,000,000 (parcel is TENANT_OCCUPIED, so incentive 0), not the design's 21,400,000/16,050,000.
- Corner `endpoints` 6 — `closeout_initiated_at` does not exist in PRD or SCAFFOLD; replaced with `viability_status == "NONVIABLE"`.
- Corner `rbac` 4 — `approved_by_user_id` and `reviewed_by_user_id` exist in neither PRD nor SCAFFOLD; replaced with `status` plus the real `validated_by_user_id == "pa-validator"`.

**Setups minimally repaired (pattern 2):**
- Corner `endpoints` 6 — added INTERESTED→DECLINE so the parcel is `ACQUISITION_CANCELLED`; otherwise INITIATE would return `ERR_INVALID_PROJECT_STATE` (state checks outrank business checks) instead of the asserted `ERR_NEIGHBORHOOD_NONVIABLE`.
- Corner `rbac` 1 — setup project built APPROVED rather than SUBMITTED, so the closing StaffAppraiser pre-event-value call is legally 200 (PRD requires `APPROVED`, else `ERR_PROJECT_NOT_APPROVED`); the state assertion became "still APPROVED".
- Corner `consistency_model` — trigger order reordered to submit *before* validating the BCA, since PRD requires the project to be `SUBMITTED` to validate; all asserted outcomes preserved.
- Corner `state_machines` S2, S3 — call ordering reordered per PRD gates.

## Step 6: Generate implementation — 2026-09-01T07:22:00.000Z

The implementation is complete and verified.

## Files created

All in `workspace/implementation/` (17 files, 3545 lines):

| file | lines | contents |
|---|---|---|
| `core.py` | 310 | 71 error IDs + HTTP statuses + messages, `ApiError`/`fail`, logical clock, Decimal/ROUND_HALF_UP helpers, month-end-clamping date math |
| `store.py` | 249 | constants, enums, 15 in-memory dicts, field ordering, `new_record`/`touch`/`serialize` |
| `web.py` | 401 | response envelope, `endpoint(*roles)` auth decorator, coordinator scoping, all structural validators, pagination |
| `calc.py` | 462 | 13 calculations + every derived-total reconciliation sweep (BCR, DOB, offer, relocation, obligation, graph components, acreage, diversion, monitoring dates) |
| `lookups.py` | 77 | 15 entity lookups (each raising its own 404) + parent-chain resolvers |
| `routes_project.py` | 305 | 11 endpoints (projects, BCAs, closeout) |
| `routes_parcel.py` | 256 | 9 endpoints (parcels, adjacency, pre-event value, participation cascades) |
| `routes_appraisal.py` | 243 | 9 endpoints (appraisals, DOB records) |
| `routes_offer.py` | 226 | 7 endpoints (offer build/present/respond/expire/withdraw) |
| `routes_relocation.py` | 198 | 7 endpoints (case, eligibility, claim, appeal) |
| `routes_closing.py` | 207 | 8 endpoints (closings, contractors) |
| `routes_demolition.py` | 252 | 11 endpoints (work orders, utility disconnections) |
| `routes_restriction.py` | 148 | 7 endpoints (deed restrictions, inspections, cure, terminate) |
| `routes_ledger.py` | 117 | 4 endpoints (program income post/list/read/reverse) |
| `app.py` | 84 | blueprint registration, `/_clock/set_current_utc`, error handlers |
| `start.sh` | 9 | guarded `pip install`, `exec python3 app.py`, honours `$PORT` |
| `requirements.txt` | 1 | `flask>=3.0.0` |

## Verification

- `python3 -m py_compile *.py` clean on all 15 modules; `__pycache__` removed.
- **73/73 endpoints** implemented — programmatic diff of the PRD endpoint table against Flask's `url_map` shows zero missing, zero extra; per-endpoint role sets match the PRD exactly (only the clock endpoint is unauthenticated).
- **71/71 error IDs** with byte-exact messages and matching HTTP statuses.
- Fresh boot verified via `bash start.sh` on high ports; storage is purely in-memory dicts, nothing seeded.
- Three end-to-end scenario scripts all pass (in `/tmp/smoke2212{,b,c}.py`, not part of the deliverable): the full acquisition lifecycle, a corner-case sweep (headers, pagination bounds, all uniqueness collisions, appraisal window overlap and revision limit, offer supersession/expiry, appeal limit, buffered-window conflict, disconnection FAILED bubble-up, ledger ordering/reversal), and the closeout happy path plus graph/cascade checks. Verified numbers include `bcr 1.551 / factor 12.409041`, offer `21500000−750000+1452500=22202500`, RHP `1797500`, rental assistance `42 months → 1890000`, `diversion_pct 30.0`, federal share `75002` (the PRD's own worked example), balance `300004`, and `INITIATE → FINALIZE → CLOSED_OUT`.

Every discrepancy the scripts surfaced turned out to be a bug in my test expectations, not the server; each was re-checked against the PRD prose. One real hardening change was made during this pass: offer `present` now re-verifies the source appraisal is still a `REVIEW` in `ACCEPTED` (PRD §3.5), ordered after the participation check.

## Interpretation decisions (PRD ambiguities)

1. `participating_parcel_count` denominator **includes `DECLINED`** (PRD §3.3), despite the scaffold calc omitting it.
2. Work-order `start` has **no** parcel-`CLOSED` precondition (PRD §3.7 is explicit).
3. Role header is **`X-User-Role`** (PRD §2.1), not the scaffold's `X-Role`.
4. `cost_share_federal_pct` band is **0.50–1.00 inclusive** (PRD §3.1), not the scaffold's `(0, 1]`.
5. `created_at`/`updated_at` use **wall-clock** time (§2.5's logical-clock list is exhaustive and excludes them); a monotonic sequence breaks `created_at` ties.
6. `expected_parcel_version` / `expected_project_version` are stored and echoed on PurchaseOffer / ledger entries (they are scaffold entity fields).
7. **Path entities resolve (404) before structural validation (422)**; body-entity existence comes after structural validation (§2.8, precedence 5).
8. SubrecipientCoordinator project ownership (403) is enforced on **writes only**, not reads/lists.
9. Decimal fields serialize as JSON numbers, so 2-dp values render as e.g. `30.0`, `0.0`, `1.5`.
10. Parcel creation recomputes `participating_parcel_count` and `neighborhood_viability_ratio` but **not** `viability_status` (§3.2 wording).
11. An inadmissible `participation_decision` value is `ERR_INVALID_REQUEST` (the endpoint declares no state error).
12. `determine-eligibility` order: `ERR_INVALID_CASE_STATE` → `ERR_OFFER_NOT_FOUND` → `ERR_RELOCATION_PERIOD_OVERLAP`.
13. Collection POSTs return **201**, action POSTs **200** (no PRD guidance); ledger `reverse` returns 200 even though it creates the mirror row.
14. A non-null `reviewed_appraisal_id` on an `INITIAL` appraisal is `ERR_INVALID_REQUEST`.
15. BCA `validate` checks project state before BCA state, per the global order rather than the narrative sentence order.
16. Closing `fund` orders `ERR_FEDERAL_SHARE_CAP_EXCEEDED` (55) **before** `ERR_RELOCATION_NOT_SETTLED` (58) per the §2.9 global list, even though §3.7 mentions relocation first; the one explicitly called-out pair (period-of-performance beats cap) is honoured.
17. `discount_rate_pct <= 0` is rejected only for `FEMA_BCA_TOOLKIT` (PRD §3.1), while `>= 1` is rejected for all methods (scaffold field constraint).
18. `CONFIRMED` against an already-`CONFIRMED` disconnection (not among the five enumerated movements) is treated as idempotent success with child+parent version bumps, since "the child's own status is unconstrained".
19. Unknown routes return 404 `ERR_NOT_FOUND` (non-catalogued); 405/400/415/500 map to `ERR_INVALID_REQUEST` 422.

## Step 7: Run tests and iterate — 2026-09-01T07:57:00.000Z

All 116 tests pass in all 8 parallel rounds, twice consecutively.

## Iterations run
2 diagnostic sweeps (iteration 1: 105/116 in every round, 11 failures, zero flakiness; iteration 2 after fixes: 116/116) plus one confirmatory sweep (116/116).

## Tests deleted
**None.** Every one of the 11 failures traced to a verbatim PRD sentence and was uniquely derivable, so no test met the STEP 1a/1b deletion bar.

## Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — added `parse_instant()` and `assert_instant_equals(actual, expected, label)`, and rewrote the pre-existing (previously unused) `assert_buffered_window()` to use them. Why: the PRD fixes the three-fractional-digit rendering only for `created_at`, `updated_at` and `api_request_timestamp`; it is silent on the rendering of `presented_at`, `expires_at`, `buffered_start` and `buffered_end`, so only the instant those fields denote is PRD-derivable. This is a STEP 1c partial-coverage split: the exact instant (including the one-second boundary offsets) is still asserted; only the PRD-silent fractional-digit formatting is dropped.

## Fixes applied to `test_suite/`
- `test_03_non_linear_state_machines.py:275` — buffered-window pair routed through `assertions.assert_buffered_window`.
- `test_08_temporal_overlap.py` (4 sites: `delta_first`, `second`, `epsilon_first.buffered_end`, `cleared.buffered_start`) — same instant-comparison routing.
- `test_15_corner_validations.py:189` — `presented_at`/`expires_at` routed through `assertions.assert_instant_equals`.
- `test_18_corner_closeout_gauntlet.py:284` — `validate_success(..., 201)` on the ledger-reversal call. Why: the suite contradicted itself — `test_09:198` and `test_13:163` explicitly demand 201 for the same endpoint while test_18 relied on the 200 default. The PRD only says "2xx", so the explicit two-against-one signal was honoured rather than weakened.

## Fixes applied to `implementation/`
- `store.py` / `new_record` + `touch` — `wall_now_str()` → `fmt_dt(clock_now())` (import updated). Why: PRD §2.5 "Every server-stamped instant is read from this clock", and §2.4 says clients never supply `created_at`/`updated_at`; two rows written under one pinned instant must carry the identical stamp. Ordering is unaffected because `sort_key` tie-breaks on `_seq`.
- `routes_parcel.py` / `record_participation` — deleted the `admitted = {...}` from-state table and its `fail("ERR_INVALID_REQUEST", ...)`. Why: no PRD sentence authorises an `ERR_INVALID_REQUEST` for an inadmissible participation transition (§2.9 level 4 enumerates a closed list that excludes it, and the 70-id catalogue has no participation-state error), and being at level 4 it wrongly pre-empted the level-11 `ERR_PRE_EVENT_VALUE_NOT_DETERMINED` that §3.3 mandates.
- `calc.py` / `case_interval` — now returns `None` for a case whose `rental_assistance_end_date` is null, with the prospective interval available only via a new `projected=True` argument. Why: §3.6 makes `rental_assistance_end_date` the exclusive upper bound, and a freshly opened case has it null, so such a peer occupies no interval; the old code fabricated a 42-month interval for undetermined peers and raised a false `ERR_RELOCATION_PERIOD_OVERLAP`.
- `routes_relocation.py` / `determine_eligibility` — uses `projected=True` for the subject case and skips peers with no interval.
- `routes_ledger.py` / `reverse_entry` — returns `web.respond_object(mirror, 201)`; the endpoint mints a new mirror entry.

No endpoint, field, side effect or seed data was added; storage remains in-memory dicts only.

### Orchestrator-side independent verification — 2026-09-01T08:05:00.000Z

The Step 7 subagent left no `results.*.json` on disk, so the orchestrator re-ran the full 8-round parallel sweep itself (`prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30`, 8 concurrent rounds). Result: `results.1.json` … `results.8.json` each **116 / 116 passed, 0 failed** — ALL GREEN. Artifacts persisted under `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-01T08:14:00.000Z

The finalized PRD is written. Summary below.

## Line counts
- `PRD.md`: 667 lines
- `PRD_FINALIZED.md`: 673 lines (+6, **+0.90%**); 10 line-level hunks, all inline revisions or single-paragraph inserts. No new sections.

## Changes (one bullet each)

- **§2.3 Pagination and List Ordering** — revise — appended that `created_at` is stamped from the logical clock so records created without an intervening clock move share one identical stamp, and every `created_at`-keyed ordering (default list sort, ledger secondary key, cascade processing orders, per-record sweeps, §3.3 component orderings) breaks such ties by server creation order — `store.py:231-236` (`sort_key`/`by_created`), `calc.py:146`, `calc.py:299`, `routes_ledger.py:15`, `web.py:399`.
- **§2.5 The Logical Program Clock** — revise — added `created_at`/`updated_at` to the set of instants read from the logical clock, plus the two derivable consequences (identical stamps for rows written under one clock value; `created_at == updated_at` absent a clock move) and an explicit carve-out that `api_request_timestamp` is wall-clock — `store.py:218`, `store.py:227`, `web.py:31`.
- **§2.5** — insert — one paragraph pinning that every datetime field stored on a resource is rendered `YYYY-MM-DDTHH:MM:SS.mmmZ` (three fractional digits), naming `presented_at`, `expires_at`, `resolved_at`, `funded_at`, `recorded_at`, `pre_event_value_determined_at`, `buffered_start`/`buffered_end`, and the re-rendered client-supplied `scheduled_start`/`scheduled_end` — `core.py:217-221`, `routes_demolition.py:39-42`, `routes_offer.py:139-140`.
- **§3.2 Two independent dimensions** — revise — `WITHDRAWN` described as the intended end state rather than "terminal", cross-referencing §3.3's absence of a from-state gate — `routes_parcel.py:112-183`.
- **§3.3 (intro)** — insert — the participation operation carries no from-state admissibility check: all four decisions are accepted from any current `participation_status`, no error exists for an unlisted transition, landing status is fixed by the decision alone, and named from-states mark where *additional* effects attach — `routes_parcel.py:123-182`.
- **§3.3 Expressing interest** — revise — widened to "from any `participation_status` other than `DECLINED`" and pinned that nothing but the parcel moves (no project recompute or `version` bump even where a count would arithmetically shift) — `routes_parcel.py:144-151`.
- **§3.3 Confirming voluntary participation** — revise — widened from-state to "identically from any other `participation_status`" — `routes_parcel.py:152-154`.
- **§3.3 Declining** — revise (2 hunks) — recast the two `DECLINE` shapes: the shallow one applies from every from-state other than `INTERESTED`, and its "no acquisition change / no offer withdrawal / no obligation movement" holds whatever `acquisition_status` the parcel holds — `routes_parcel.py:155-166`.
- **§3.3 Withdrawing after confirming** — revise — widened from-state; `WITHDRAWN` reworded from "terminal — there is no path out" to "the intended end of the participation dimension" — `routes_parcel.py:167-178`.
- **§3.6 Determining eligibility** — insert — one paragraph: a peer whose `rental_assistance_end_date` is null occupies no interval and is skipped whatever its `status`; the subject's interval is prospective (`start` + 42 months for `TENANT_90_DAY`, else 0), and the empty-interval case still runs the same strict test (colliding only with a peer that strictly straddles the start) — `calc.py:116-130`, `routes_relocation.py:117-130`.
- **§3.6 The withdrawal cascade** — revise — recap widened from "moves from `VOLUNTARY_CONFIRMED` to `WITHDRAWN`" to "moves to `WITHDRAWN` from any from-state" — `routes_parcel.py:167-174`.
- **§3.9 Reversing an entry** — revise — response status pinned to HTTP 201 because the operation mints the mirror row — `routes_ledger.py:117`.

## Per-edit pre-edit search log

1. **§2.3 tie-break.** (a) Subject: ordering of records by `created_at`. (b) Enumerated/grepped: `store.sort_key`/`by_created` (store.py:231-236), all 8 `by_created` callsites (calc.py:209,326,330,334,350,458; routes_parcel.py:105,170; routes_project.py:147,152; routes_offer.py:77; routes_relocation.py:107), `calc.dob_sweep_order:146`, `calc.ledger_order:299`, `routes_ledger._ledger_sort:15`, `web.list_response:399`, `recompute_components` node ordering + component tie-break (calc.py:209,227,243-251). (c) Wording widened from "the default list sort" to an explicit enumeration of *every* `created_at`-keyed ordering, and phrased as "order in which the server created the records" (never `id`) so it stays consistent with §3.3's "a parcel's `id` is never used as a tie-break" and §3.5/§3.9's "`id` is never used as a sort key".

2. **§2.5 clock-sourced audit stamps.** (a) Subject: which instants read the logical clock. (b) Enumerated: `store.new_record:218`, `store.touch:227`, all `fmt_dt(clock_now())` sites (routes_parcel.py:96, routes_offer.py:139-140, routes_closing.py:89,120, routes_demolition.py:233), `core.wall_now_str:224` and its single consumer `web._meta:31`, `app.py:47-49` (clock endpoint mutates nothing). (c) Added the explicit `api_request_timestamp` carve-out so the broadened "read from this clock" claim does not capture the one instant still taken from wall time.

3. **§2.5 instant rendering.** (a) Subject: rendered shape of stored datetimes. (b) Enumerated: `core.fmt_dt` (three-digit, always `Z`) and every writer — store.py:218,227; routes_parcel.py:96; routes_offer.py:139-140; routes_closing.py:89,120; routes_demolition.py:39-42,233; plus `core.parse_datetime` (accepts 1–9 fractional digits/offsets on input) and `app.py:49` which echoes the raw `current_utc` string. (c) Scoped the sentence to "every datetime field stored on a resource" so the clock endpoint's raw echo is excluded, and explicitly covered the client-supplied `scheduled_start`/`scheduled_end` as *re-rendered* rather than stored verbatim.

4. **§3.2 / §3.3 participation edits (5 hunks).** (a) Subject: `participation_status` transitions and their side effects. (b) Enumerated: `routes_parcel.record_participation:112-183` branch by branch, `_cancel_acquisition_pipeline:101-109`, `calc.recompute_participating:195`, `recompute_holdout:202`, `recompute_components:208`, `recompute_ratio:276`, and every other reader of `participation_status` — `routes_offer.py:49` (offer create gate), `routes_offer.py:127` (present gate), `routes_offer.py:166` (owner-response ACCEPT gate), `routes_appraisal.py:60` (INITIAL-appraisal side effect), `calc.py:198,204` (counts), `routes_parcel.py:63,70` (list filter). (c) Scoped the no-gate claim strictly to "this operation" so the downstream `VOLUNTARY_CONFIRMED`/`INTERESTED` gates in routes_offer and routes_appraisal keep their force; softened "terminal" to "intended end state" in both places rather than deleting it; widened the shallow-`DECLINE` sentence from a `NOT_CONTACTED`-specific justification ("no parcel in `NOT_CONTACTED` can have reached an acquisition milestone") to a status-agnostic statement, since the shallow branch now also fires for `VOLUNTARY_CONFIRMED` parcels that do have offers; and stated the "nothing else moves" for `INTERESTED` as an absolute rather than implying a recompute, matching the impl's stale `participating_parcel_count` on `WITHDRAWN`→`INTERESTED`.

5. **§3.6 rental-assistance interval.** (a) Subject: the overlap interval and `rental_assistance_end_date`. (b) Enumerated: `calc.case_interval:116-130` (both branches), its only two callsites `routes_relocation.py:117` (subject, `projected=True`) and `:125` (peer, default), `calc.rental_assistance:86-99` (the end date actually stored), `calc.relocation_benefits:102-113`, `routes_relocation.create_case:58` (end date opens null), and the peer loop's filters at `:118-129` (no `status` filter). (c) Split the paragraph into subject vs peer rather than one universal rule; added "whatever its `status`" because the peer loop applies no status filter; kept the empty-interval consequence descriptive ("collides only with a peer interval that strictly straddles its start") instead of claiming a zero-month case can never overlap.

6. **§3.9 reversal status code.** (a) Subject: HTTP status of `POST /program-income-entries/{entry_id}/reverse`. (b) Enumerated every `respond_object(..., 201)` in the tree (routes_project.py:67,248; routes_parcel.py:56,224; routes_appraisal.py:63,203; routes_offer.py:86; routes_relocation.py:70; routes_closing.py:42,174; routes_demolition.py:56,192; routes_restriction.py:82; routes_ledger.py:62,117) and confirmed the contrasting 200 returns on action endpoints (`routes_closing.record_closing:143` — which creates a restriction yet returns 200 with the closing, `routes_appraisal` review-decision, dob reverse, contractor status). (c) Deliberately kept the claim local to this one endpoint instead of stating a general "creations return 201" rule, which `record_closing` would contradict.

## Step 9: Complete PRD — 2026-09-01T08:32:00.000Z

PRD_COMPLETED.md is finished and verified.

## Verification
- `PRD_FINALIZED.md`: 673 lines / 132,496 chars → `PRD_COMPLETED.md`: 674 lines / 143,542 chars (**char delta +11,046**; +1 line, from one added bullet inside the existing §2.2 error-format list — no new section).
- `## ` sections: **identical** (diff clean). `### ` subsections: **identical**.
- Markdown tables intact: 148 pipe rows in both; 73 endpoint rows (= 73 impl routes), 71 error-catalogue rows (= 71 ids in `core.ERROR_STATUS`).
- File ends non-truncated with `| ERR_DUPLICATE_HOUSEHOLD_REFERENCE | 409 |`.

## Change counts
**40 edits — 33 ambiguity-pins, 7 mismatch-revisions.**

## Per-change log
- §2.1 — insert — ambiguity — absent/empty/unrecognised `X-User-Role` yields `ERR_UNAUTHORIZED`, not a structural error — web.py:96-98
- §2.1 — insert — ambiguity — coordinator scope compares after path-parent resolution (before existence when the project id is body-supplied), and guards writes only — every list/retrieve endpoint is unscoped — web.py:106-109, routes_parcel.py:116 vs routes_parcel.py:199
- §2.2 — insert — ambiguity — every row-minting POST answers 201 (incl. the ledger reversal mirror); all else 200 — routes_project.py:67, routes_ledger.py:117
- §2.2 — insert — ambiguity — bad JSON / non-object body / disallowed method = `ERR_INVALID_REQUEST` 422; unroutable path = off-catalogue `ERR_NOT_FOUND` 404; absent body read as `{}` — app.py:55-70, web.py get_body
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected; enum filters validated, id/free-text filters not, boolean filters accept `true/false/1/0` case-insensitively; unknown params ignored — web.py:367-388
- §2.5 — revise — ambiguity — clock endpoint echoes `current_utc` as the exact supplied string, not re-rendered — app.py:48
- §2.5 — insert — ambiguity — dates strict `YYYY-MM-DD` and echoed verbatim where stored raw; datetimes accept `Z`/offset/naive/space-separator, optional seconds, stored at 3 fractional digits — core.py `_DATE_RE`/`parse_datetime`, routes_project.py:60
- §2.6 — insert — ambiguity — excess decimal places rejected not rounded; numeric fields must be JSON numbers (strings/booleans rejected); all quantities rendered as JSON numbers — web.py:218-245, web.py `_plain`
- §2.7 — insert — ambiguity — `expected_parcel_version` / `expected_project_version` retained and echoed on the created row; null on a reversal mirror — store.py:206-210, routes_ledger.py:109
- §2.9 step 1 — insert — ambiguity — whitespace-only `X-User-ID` counts as empty — web.py:94
- §2.9 step 2 — insert — ambiguity — the coordinator scope bar fires at step 5 and the appraisal-authorship bar inside step 4, both still `ERR_UNAUTHORIZED` — routes_appraisal.py:21-23
- §2.9 step 4 — insert — ambiguity — `discount_rate_pct` ≥ 1.00 is structural under either method — routes_project.py:224
- §3.1 — insert — ambiguity — `discount_rate_pct` < 1.00 always; ≤ 0 admissible under `PRE_CALCULATED_BENEFIT`; attaching a BCA moves no project field — routes_project.py:221-224, routes_project.py:248
- §3.1 — insert — ambiguity — `return_reason` mandatory and non-empty — routes_project.py:114
- §3.2 — insert — ambiguity — parcel creation refreshes only count+ratio, leaving `viability_status` stale across a band crossing — routes_parcel.py:53-54
- §3.3 — insert — ambiguity — `CONFIRM_VOLUNTARY` touches the project not at all even from `WITHDRAWN`/`DECLINED`; signed date stored verbatim — routes_parcel.py:150-152
- §3.3 — revise — mismatch — `WITHDRAW` also recomputes `federal_obligated_cents`, and pointedly does **not** recompute `holdout_parcel_count` (stale after withdraw-from-`DECLINED`) — routes_parcel.py:167-176
- §3.3 — revise — mismatch — the viability "whole family" sentence is a trigger list, not a promise all six move at each trigger; narratives are authoritative — routes_parcel.py:141-176
- §3.4 — insert — ambiguity — role/`appraisal_type` match evaluated inside the structural stage, right after the enum check and before all other fields — routes_appraisal.py:19-23
- §3.4 — insert — mismatch — SoD-1 second limb is evaluated before `decision` is read, so it bars `RETURN`/`REJECT` too — routes_appraisal.py:130-135
- §3.5 — insert — ambiguity — offer gate list is topical; §2.9 order governs (`ERR_DOB_EXCEEDS_BASE_VALUE` before `ERR_VALUATION_BASIS_MISMATCH`; OCC before project-approval) — routes_offer.py:33-86
- §3.5 — insert — ambiguity — on present, the acquisition-dimension check (also `ERR_INVALID_OFFER_STATE`) outranks the participation check — routes_offer.py:118-134
- §3.6 — insert — ambiguity — opening a case consults no project/parcel state and moves nothing outside the case — routes_relocation.py:27-70
- §3.6 — insert — ambiguity — more than one `ACCEPTED` offer is not an error; the earliest by `created_at` supplies the price — routes_relocation.py:106-111
- §3.7 — insert — ambiguity — no uniqueness on closing↔accepted-offer; scheduling moves no parcel/project field — routes_closing.py:16-42
- §3.7 — insert — ambiguity — funding check order is POP → cap → relocation settlement — routes_closing.py:69-84
- §3.7 — revise — mismatch — parcel state is never a ground for refusing a work order; contractor resolved after structural validation; a `SUSPENDED` contractor may still be issued one — routes_demolition.py:24-52
- §3.7 — revise — mismatch — six admitted disconnection movements: `CONFIRMED` from an already-`CONFIRMED` child overwrites reference/`resolved_at` and bumps both versions — routes_demolition.py:232-241
- §3.7 — insert — mismatch — completion's parcel move is conditional on the parcel standing at `CLOSED`; otherwise the parcel and its `version` are untouched and completion still succeeds — routes_demolition.py:136-137
- §3.8 — insert — ambiguity — a `prohibited_use_code` outside the restriction's array is `ERR_INVALID_REQUEST` at the structural stage, ahead of state and future-dating checks — routes_restriction.py:49
- §3.8 — insert — mismatch — a `COMPLIANT` finding against `IN_COMPLIANCE` or `VIOLATION_OPEN` changes nothing (no re-anchor, no violation close); row still created, `version` still +1 — routes_restriction.py:72-75
- §3.8 — insert — ambiguity — a parcel with no restriction row contributes no acreage; a parcel with several counts once as soon as one is not `TERMINATED` — calc.py:353-358
- §3.9 — insert — ambiguity — mirror copies `project_id`/`applied_to_parcel_id`/`entry_type`/`amount_cents`/`posted_on`; `federal_share_cents` is the exact negation, not re-derived; `reversal_note` validated but never stored — routes_ledger.py:95-109
- §4 `GET /mitigation-projects` — revise — ambiguity — filters `status`, `grant_program`, `viability_status` — routes_project.py:73-75
- §4 `GET /benefit-cost-analyses` — revise — ambiguity — filters `project_id`, `analysis_method`, `status` — routes_project.py:254-256
- §4 `GET /parcels` — revise — ambiguity — adds `occupancy_type` filter — routes_parcel.py:62-65
- §4 `GET /parcel-adjacencies` — revise — ambiguity — `parcel_a_id`/`parcel_b_id` are positional, matching only the stored end named — routes_parcel.py:230-232
- §4 `GET /dob-records` — revise — ambiguity — adds `benefit_source` filter — routes_appraisal.py:209-211
- §4 `GET /relocation-cases` — revise — ambiguity — adds `household_reference` filter — routes_relocation.py:77-80
- §4 `GET /demolition-contractors` — revise — ambiguity — filters `status` and boolean `asbestos_certified` — routes_closing.py:180-181

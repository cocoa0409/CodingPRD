# Worklog — task_2264_underground_heating_oil_tank_removal

## Step 1: Create Task Directory — 2026-09-01T12:40:49.976Z

Created `tasks/task_2264_underground_heating_oil_tank_removal/` and `tasks/task_2264_underground_heating_oil_tank_removal/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T14:03:00.000Z

Done. All three scaffold artifacts are complete and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/SCAFFOLD.yaml` (2836 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2500 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/SCAFFOLD_CORNER_DESIGN.yaml` (3778 lines)

## SCAFFOLD.yaml (§1.0–§1.7)
`difficulty_level: expert_plus`, `api_prefix: "/"`, consistency `immediate`, role model `segregation_of_duties`, complexity layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`.
- **12 entities** (Property, TankProject, HomeownerDisclosure, Permit, Crew, DecommissionWorkOrder, Laboratory, SoilSample, RemediationChangeOrder, TrustFundClaim, NFALetter, InsuranceNotification)
- **10 state-machine blocks over 8 entities** (DecommissionWorkOrder carries two parallel dimensions, `field_status` + `billing_status`)
- **8 calculations**: `decommission_method_recommendation` (weighted_scoring), `contamination_classification` (threshold), `remediation_soil_volume` (dual-variant PROVISIONAL_GRID / FINAL_SURVEYED), `remediation_cost` (round-per-line then sum), `trust_fund_eligible_amount` (dual-variant, cap-tier keyed on gross before deductible), `insurance_reserve_allocation` (waterfall), `nfa_blocker_set` (7 sorted codes), `laboratory_timing`
- **30 validations** on a strict priority ladder 10→78, **48 error codes**, **49 endpoints**, **6 roles**, **2 OCC concurrency rules** (both on `expected_project_version`: `POST /change-orders`, `POST /trust-fund-claims`)

## §1.8 difficulty design
9 rule categories / **23 instances** (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2 — depth 5 and depth 4, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).

## §1.9 corner design
All **9 required sections**, **84 instances = 50 full test recipes + 34 `excluded_because` stubs**: entities 13, state_machines 16, calculations 13, validations 5, endpoints 4, errors 24, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. Both concurrency rules have their own dedicated OCC stale-version instance (412 + `version`-increments-by-1 asserts).

## Audit notes
- **Error coverage: 48/48.** Every code is either triggered by an asserted `== ERR_…` or stubbed to a §1.8 instance that triggers it. Three codes that §1.8 only asserts *negatively* (`ERR_EXCAVATION_LIMIT_EXCEEDED`, `ERR_DISCLOSURE_EXPIRED`, `ERR_SUPERSEDE_TARGET_INVALID`) were given real triggers in §1.9 rather than stubs.
- All 34 stub citations resolve to an existing `rule_id / name` pair in §1.8; no stub carries a `test_recipe`; all 107 instance names are unique across the union of both design files.
- Claim-type vocabulary is drawn only from `claim-extraction-guide.md` rows; a comment records that the scaffold has no bulk or junction-link endpoints, so those guide rows have no applicable instance.
- Cross-table fix applied during authoring: `TankProject SURVEYED→VOID` was missing the work-order abort cascade that the `DecommissionWorkOrder` table already referenced; added (`abort_reason = 'PROJECT_VOIDED'`, `billing_status -> WRITTEN_OFF`, `open_project_count` decrement).
- Role fixes found by review/lint: trust-fund claim create/submit are ComplianceOfficer-exclusive (initially authored as LSP); the RBAC denial sweep needed a live `${pv1}` instead of a literal OCC version.
- No forbidden concurrency vocabulary, no random/UUID business decisions, every chain sets the logical clock explicitly at or after `2026-08-01T00:00:00Z`.
- **Hard constraint honored**: no sibling `task_*/` directory or artifact was listed, globbed, grepped, or read at any point.

Final lint verdict:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 49   §1.1 entities declared: 12
  §1.8 instances scanned: 23    §1.9 instances scanned: 50
  Calls scanned (§1.8+§1.9): 1157
```

## Step 3: Copy Shared Files — 2026-09-01T14:04:26.366Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2264_underground_heating_oil_tank_removal/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T14:20:21.903Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/workspace/PRD.md` (88.8 KB, ~12,200 words). The two design-index files were never opened, grepped, or referenced.

## Structure produced

- `# Oil Tank Remediation API — Product Requirements Document`
- **§1 Introduction** — 3 paragraphs from `scenario` (compliance-audit framing, segregation of duties, no-stale-derived-state).
- **§2** — 11 subsections: 2.1 roles/auth/segregation, 2.2 response envelope (byte-verbatim from `section-2.2-response-structure.md`), 2.3 pagination, then 7 domain-derived cross-cutting subsections (identity & version counter, logical site clock, flat-graph reference resolution, cascade discipline & recomputation order, OCC as "authoring against a current view", units/precision/rounding, boundary conventions, order of rejection).
- **§3** — 9 lifecycle-derived subsections (intake/sweep survey → disclosure → permitting → crew scheduling & field dimension → billing dimension & surveyed volume → sampling/custody/lab → remediation scoping & cost → insurance waterfall → trust fund/NFA/settlement). Deliberately not the example PRD's shape.
- **§4** — status-code paragraph + 4-column table, **49/49 endpoints**, roles verified equal to the scaffold set-for-set on every row.
- **§5** — 2-column table, **48/48 error IDs**. Document ends there; no audit footer.

## Hard Contract audits (mechanically verified)

1. **Field-Name Coverage — PASS.** All 122 distinct scaffold `fields[].name` + `request_body`/`input`/`query_params` identifiers appear verbatim in backticks (0 missing), plus the 4 common fields, both headers, all 6 role names, all 4 pagination fields, and the non-entity identifiers `expected_project_version`, `to_iso8601`, `current_utc`, `open_change_order_count`, `current_round_sample_count`.
2. **Rule Coverage — PASS.** All 66 transitions across 10 state-machine dimensions covered, with every `from`/`to`/initial/terminal state named in backticks (0 missing); all 48 error IDs; all enum members of every field (0 missing); all 7 blocker codes; the full 30-entry validation precedence ladder in scaffold priority order with `applies_to` scopes; both OCC rules; all 8 calculations with every constant translated to prose (clamp-before-round on `method_score`, round-per-line-then-sum on `line_amount_cents`, S1–S8 pinned claim order and the PRELIMINARY/FINAL cap-vs-deductible inversion, the three-bucket waterfall with the conditional third-party capacity and the exact-cents conservation invariant, both volume variants, strict-greater-than classification, lexicographic blocker sort).
3. **§3 Path Purity — PASS.** Zero `/`-leading backtick tokens, zero bare HTTP verbs, zero method+path tokens in §3; every endpoint referenced by state-transition framing, role+action verb, or capability description.

Also verified: no pseudocode operators (`>=`, `==`, `IN {`, `min()`, `round_half_up()`, `+=`) anywhere in prose; no fuzzy quantifiers ("approximately"/"roughly"/"conservatively"/hedged "generally"/"normally" — three instances were found and removed); OCC framed purely as stale-version rejection with no "simultaneous"/"race" language.

## Scaffold issues found

The header comment at `SCAFFOLD.yaml:49-50` is stale in three counts (comment-only; the rule bodies themselves are self-consistent and were transcribed from the actual entries):
- claims "43 error codes" — `errors[]` has **48**
- claims "7 calculations" — `calculations[]` has **8**
- claims "9 state-machine dimensions across 8 entities" — there are **10 dimensions across 9 entities**

"12 entities / 49 endpoints" both check out. Separately, `ERR_PERMIT_NOT_ISSUED` has no priority entry of its own — it is folded into the priority-51 check alongside `ERR_PERMIT_EXPIRED`; the PRD documents them in that internal order.

## Step 5: Generate Unit Tests — 2026-09-01T15:49:37.743Z

All work is complete. Final state and findings:

## Files written

**Stage 2 (this session):**
- `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/test_suite/test_16_rbac.py` — 1 test (rbac)
- `.../test_suite/test_17_cross_cutting_layers.py` — 2 tests (optimistic concurrency on change-order and claim creation)
- `.../test_suite/test_18_consistency_model.py` — 1 test (same-instant visibility of the decline cascade)

**Stage 1 (amended):** `.../test_helpers/assertions.py` gained `parse_instant()` / `assert_same_instant()`.

## Coverage (design-index-only, audited programmatically)

| Queue | Instances | Tests |
|---|---|---|
| A (Difficulty §1.8) | 23 / 23 non-stub, all ≥2 tests | 49 |
| B (Corner §1.9) | 50 / 50 non-stub | 50 |
| **Total** | **73 instances** | **99 tests** |

Queue B by section: entities 12, state_machines 12, calculations 4, validations 2, endpoints 3, errors 13, rbac 1, cross_cutting_complexity_layers 2, consistency_model 1.

**Skipped instances: none required skipping** — all 34 `excluded_because:` stubs were left untranslated (as specified), and every non-stub instance passed the PRD-first two-condition filter.

## Audits (all clean)
- Every `Design:` tag resolves to a real non-stub `name:`; no dual-tagged or untagged tests; exactly one tag per docstring.
- All 244 PRD citations survive a literal grep of `workspace/PRD.md`.
- No unused imports; `py_compile` clean on `test_suite/` and `test_helpers/`; no "scaffold"/design-yaml leakage in generated code.
- **Executed the suite against the reference implementation via `prd-bench-local-run --isolation per-test-server`: 99/99 passed** (note: `--start-command` and `--test-dir` must be absolute, since per-test restarts run with cwd set to the test dir).

## Corrections made while validating
1. **Vacuous ladder-order assertions (6 sites, test_05 and test_15).** `validate_error()` returns the error *dict*, not the id string, so `error_id != ApiErrorId.X.value` was always trivially true. Now `validate_error(...)["error_id"]`.
2. **Timestamp equality (24 sites across 14 files).** Stamped timestamps serialize with three fractional digits (`2026-08-03T08:00:00.000Z`); the PRD pins the instant and ISO 8601 UTC, not a zero-fraction spelling. All such assertions now compare `parse_instant(actual) == parse_instant(expected)`, keeping their descriptive messages.
3. **Design-recipe defect in the holding-time boundary instance** (`boundary_precision_check/holding_time_exactly_at_limit_is_compliant_one_second_past_is_not`). PRD §2.9 rounds `holding_time_elapsed_hours` half up to 2 dp *before* comparison, so one second past 336 h still rounds to 336.00 and is compliant — the recipe's trigger could not produce the breach it asserts. The breach instant is now one minute past (336.02 h), with the round-before-compare sentence added as a citation; intent preserved, nothing weakened.
4. **Three invalid `sample_point` values in the corner yaml** (`DEEP_CLEAN_POINT`, `ROUND_TWO_FLOOR`, `RETEST_POINT` — none declared by PRD §3.6) were mapped to declared points at the same depths: `TANK_BOTTOM`/96, `NORTH_SIDEWALL`/72, `SOUTH_SIDEWALL`/84.
5. **Envelope key-count slip** in the `entities` design instance (claims two top-level keys; PRD §2.2 declares three: `meta`, `response_type`, `data`) — handled by `assert_envelope_has_only_meta_and_data`.

## Step 6: Generate Implementation — 2026-09-01T15:49:37.743Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/workspace/implementation/` (18 files, ~2,700 lines):

- `start.sh` — `cd` to its own dir, guarded `pip install -r requirements.txt` only if Flask is missing, then `exec python3 app.py`; `requirements.txt` (`Flask==3.0.3`)
- `app.py` — factory, blueprint registration, per-request lock + audit bookkeeping, `ApiError`/`HTTPException`/`Exception` handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (12 tables, empty at boot, **no seeding**), logical clock, `create/assign/mark/commit/serialize/sort_rows`
- `errors.py` — all 49 error ids → (status, message); `response.py` — `meta`/`response_type`/`data` envelope + pagination meta
- `calculations.py` — all 7 pinned calculations plus every constant and enum vocabulary; `middleware.py` — auth, role gates, entity-backed ownership, FK resolution, typed field validators, pagination/filters
- `services/project.py` — TankProject derived state, blocker set, cost/waterfall recomputation, cascades
- `routes/` — 13 blueprints: properties, projects, disclosures, permits, crews, work_orders, laboratories, soil_samples, change_orders, claims, nfa_letters, insurance, clock

## Endpoint count
**49** registered rules (excluding Flask's static), matching the SCAFFOLD endpoint table exactly.

## Notable design decisions
- **Audit versioning**: per-request dirty set gives exactly one `version += 1` + `updated_at` refresh per mutated row; rows created in the same request stay at version 1; the three documented explicit `TankProject.version` bumps (sweep survey, change-order create, claim create) go through `mark()`.
- **Bug found and fixed this pass**: `commit()` ran only in `after_request`, so mutation responses serialized the *pre-bump* `version`/`updated_at` (e.g. sweep survey returned `version: 1` instead of `2`). `entity_response`/`list_response` now flush pending bookkeeping before serializing; `after_request` remains as a safety net for error paths.
- **Persist-then-reject** flows (disclosure expiry, municipal-permit lapse at mobilization, holding-time invalidation) commit before raising, so the recorded lapse survives the 4xx.
- **Error ladder**: only supplied FKs are resolved (404) before full shape validation (422), so a *missing* required FK is a 422 and a *bad* one is a 404; ownership checks precede pagination; `GET /properties/{id}` compares the path id before resolution.
- **PRD/SCAFFOLD conflict** on the RECEIVE gate order resolved 2-of-3 in favour of accreditation → lab capacity → holding time.
- Decimal + ROUND_HALF_UP throughout, money as integer cents; `created_at ASC` ordering made deterministic under a frozen clock via a monotonic internal `_seq` tiebreak.

## Verification
- Fresh-process boot via `bash start.sh` succeeds, binds `$PORT` on 0.0.0.0, exits cleanly on SIGTERM (returncode −15) — compatible with `--isolation per-test-server`. Fresh boot shows `total_count: 0` on every collection and clock exactly `2026-08-01T00:00:00.000Z`.
- Two ad-hoc suites (~200 assertions, `/tmp/smoke2264.py`, `/tmp/edge2264.py`) run against a fresh boot: full happy path (property → project → sweep → disclosure → permits → work order → samples → 5-level result cascade → change order → claim → NFA issue → rescind 4-level cascade → re-close → PAID settlement) **0 failures**; edge suite (score-55 boundary, disclosure expiry + exact-limit boundary, method override, buffered crew calendar, lab capacity/holding-time/turnaround-breach, retest chain, excavation ceiling + supersession, hazardous multiplier, third-party waterfall, NY tier-2 caps, info-request limit, final-settlement withdrawal/duplicate, void and permit-revocation cascades, permit-expiry-at-mobilize) **0 real failures** — the single reported mismatch was a wrong expectation in my scratch script (`ERR_SOIL_SAMPLE_NOT_FOUND` is the PRD-correct code).
- Test server stopped; `__pycache__` cleaned. `test_helpers/` and `test_suite/` were never read.

## Step 7: Run Tests and Iterate — 2026-09-01T15:54:02.456Z

The diagnostic loop terminated on the first iteration — the task was already clean.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep; no second iteration needed since the exit condition was met immediately).

**Sweep result:** all 8 concurrent rounds green — `99 passed / 99 total`, `failed 0`, `errors 0`, `skipped 0`, ~137 s wall per round under `--isolation per-test-server`. No flakiness surfaced: the pass set was identical across all 8 rounds, so the union of failing tests is empty and the diagnostic protocol (STEPs 0–3) had nothing to operate on.

**Tests deleted:** none. No test failed in any round, so no PRD-silence or unique-derivability collapse review was triggered.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

**Cardinal-rule spot checks performed (all clean):**
- No `skip` / `xfail` markers anywhere in `test_suite/` or `test_helpers/` — the 99 passes are real executions, not silently-skipped tests.
- No disk persistence or startup seeding in `implementation/` — grep for `sqlite`, `open(`, `json.dump`, `/tmp`, `pickle`, `shelve` across all implementation `.py` files returns nothing; storage is in-memory dicts only (`workspace/implementation/db.py`).

**Notes on prior state:** `worklog.md` records that the test-generation stage had already corrected five test-side defects before I arrived (vacuous ladder-order assertions where `validate_error()` returns a dict rather than an id string; 24 timestamp-equality sites relaxed to instant comparison via `parse_instant()`; a holding-time boundary recipe that rounded to compliant before comparison; three `sample_point` values not declared by PRD §3.6; an envelope key-count slip), plus one implementation defect (`commit()` running only in `after_request`, so mutation responses serialized pre-bump `version`/`updated_at`). Those fixes are consistent with what the green sweep now confirms, and I found no residual issues on top of them.

Relevant paths: `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/workspace/implementation/`, `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/test_suite/`, `/home/ubuntu/github/CodingPRD/tasks/task_2264_underground_heating_oil_tank_removal/test_helpers/`, results at `workspace/implementation/results.{1..8}.json`.

Orchestrator verification: all 8 `results.{1..8}.json` re-read directly — each reports `passed=99, total=99, failed=0, errors=0, skipped=0`.

## Step 8: Finalize PRD — 2026-09-01T15:54:02.456Z

SKIPPED per the skill's skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline — so no `<step_7_diff>` hand-off exists and no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-09-01T16:08:31.337Z

The patch is complete and verified. `PRD_COMPLETED.md` exists at the target path, was produced by `cp workspace/PRD.md workspace/PRD_COMPLETED.md` followed by 45 in-paragraph edits, and the diff confirms 43 changed-line hunks with the line count unchanged at 461 — no new sections, no new paragraphs, no deletions. Every edit is either an inline insert into an existing sentence/bullet or an inline revision of one.

**Files**

| | lines | chars |
|---|---|---|
| `workspace/PRD.md` (source) | 461 | 89,085 |
| `workspace/PRD_COMPLETED.md` | 461 | 100,087 |

Char-delta: **+11,002**. Diff hunks: 43 (45 logical changes; line count unchanged — all edits in-paragraph).

**Counts**: 38 ambiguity-pins, 7 mismatch-revisions.

**Mismatch-revisions**

- §2.1 Roles & ownership — insert — mismatch — ownership vs path-resolution order: property read decides ownership before resolving the id (403 on an unknown id), whereas every other gated operation lets the addressed row's 404 precede the 403 — `routes/properties.py:47`, `routes/disclosures.py:77-81`, `routes/nfa_letters.py:58-61`
- §2.4 Audit fields — revise — mismatch — `version` advances by exactly 1 per *mutating request*, not per field write; the response body already carries the advanced `version`/`updated_at` — `db.py:90-127`, `response.py:32-36`
- §3.2 Disclosures — revise — mismatch — expiry is evaluated first among the substantive checks, i.e. after body-shape validation and the `PENDING`-state test that §2.11 places above it — `routes/disclosures.py:92-104`
- §3.3 Permits — revise — mismatch — at mobilization every lapsed issued municipal permit flips to `EXPIRED` and blockers recompute; `ERR_PERMIT_EXPIRED` is raised only when *all* issued municipal permits have lapsed — `routes/work_orders.py:171-183`
- §3.6 Sample receipt — revise — mismatch — gates run accreditation → capacity → holding time; a capacity refusal leaves the sample `IN_TRANSIT` and never computes `holding_time_elapsed_hours` — `routes/soil_samples.py:150-181`
- §3.7 Change orders — revise — mismatch — submission identity is not policed: any `LicensedSiteProfessional` may submit, `X-User-ID` is never compared to `requested_by_user_id`, and change-order state is tested before project state — `routes/change_orders.py:84-97`
- §3.9 NFA issuance — insert — mismatch — preconditions tested in ladder order (letter state, project state, segregation of duties, blockers, closing date), with blockers recomputed immediately before examination — `routes/nfa_letters.py:71-83`

**Ambiguity-pins**

- §2.2 Envelope — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics; `api_request_timestamp` reads the logical clock — `response.py:13-21`
- §2.3 Pagination — insert — ambiguity — unparseable `limit`/`offset` yield `ERR_INVALID_PAGINATION` rather than falling back to defaults — `middleware.py:242-260`
- §2.3 Ordering & filters — insert — ambiguity — `created_at` ties broken by insertion order; filters are exact equality; an unparseable numeric filter (e.g. `sampling_round`) matches no row — `db.py:148-150`, `middleware.py:271-279`
- §2.4 Audit fields — insert — ambiguity — `created_at`/`updated_at` read the logical clock and are equal on a fresh row; writing a field its existing value is not a mutation — `db.py:97-114`
- §2.5 Clock — insert — ambiguity — the clock response's `data` carries only `current_utc`; `to_iso8601` is required — `routes/clock.py:16-19`
- §2.6 References — insert — ambiguity — which body references are mandatory (422, not 404) and that all identifiers resolve before presence is complained about — `routes/work_orders.py:25-32`, `routes/soil_samples.py:26-39`
- §2.8 Optimistic concurrency — insert — ambiguity — `expected_project_version` must be an integer; absent or non-integer is 422 before any comparison — `routes/change_orders.py:32`, `routes/claims.py:43`
- §2.11 rule 6 — insert — ambiguity — whitespace-only required strings count as absent; undeclared fields are ignored — `middleware.py:109-115`
- §3.1 Properties — insert — ambiguity — coverage figures are integer cents — `routes/properties.py:24-25`
- §3.1 Tank location — insert — ambiguity — tank descriptors and `tanks_detected_count` are non-negative integers, and a non-`INTAKE` project yields `ERR_PROJECT_STATE_INVALID` before the tank-located check — `routes/projects.py:103-120`
- §3.1 Project summary — insert — ambiguity — the summary carries exactly ten fields (no id/audit fields) and `current_round_sample_count` counts every sample in the round regardless of status — `services/project.py:277-289`
- §3.2 Disclosures — insert — ambiguity — sending has no project-state gate; Homeowner list scoping, and a foreign `tank_project_id` filter yields `ERR_NOT_RESOURCE_OWNER` — `routes/disclosures.py:21-71`
- §3.2 Decline — insert — ambiguity — a decline in any other configuration voids nothing — `routes/disclosures.py:116-123`
- §3.3 Permit filing — insert — ambiguity — no project-state gate; a missing reason is 422 before state checks; permit state precedes project state — `routes/permits.py:21-91`
- §3.3 Permit decisions — insert — ambiguity — a wrong project state on an `ISSUED` decision yields `ERR_PROJECT_STATE_INVALID` — `routes/permits.py:90-91`
- §3.4 Scheduling — insert — ambiguity — work-order creation consults no project `status` — `routes/work_orders.py:21-56`
- §3.4 Method override — insert — ambiguity — a null `recommended_method` makes every chosen method an override — `routes/work_orders.py:43`
- §3.4 MOBILIZE — insert — ambiguity — order of the mobilization checks — `routes/work_orders.py:118-123`
- §3.4 COMPLETE — insert — ambiguity — non-negative figures required, project moves to `DECOMMISSIONING`, and `sampling_round` steps 0→1 only when it is 0 — `routes/work_orders.py:134-149`
- §3.5 RECONCILE — insert — ambiguity — precondition order and the exact error codes — `routes/work_orders.py:198-206`
- §3.6 Laboratories — insert — ambiguity — lab parameters are integers and `accredited` is a boolean — `routes/laboratories.py:17-20`
- §3.6 Sample creation — insert — ambiguity — permitted project states, `depth_inches` an integer, `qc_flag`/`turnaround_breach` defaults — `routes/soil_samples.py:41-80`
- §3.6 Reopening — insert — ambiguity — an open change order blocks with `ERR_PROJECT_STATE_INVALID`, checked before the retest check — `routes/soil_samples.py:44-54`
- §3.6 Custody — insert — ambiguity — event/role pairing violations raise `ERR_ROLE_NOT_PERMITTED` — `routes/soil_samples.py:125-128`
- §3.6 Result posting — insert — ambiguity — no project-state precondition — `routes/soil_samples.py:193-194`
- §3.6 Round completion — insert — ambiguity — evaluated only while the project is `SAMPLING` — `services/project.py:209-215`
- §3.6 Retraction — insert — ambiguity — round-mismatch code and position, and that fiscal figures are left untouched — `routes/soil_samples.py:222-235`
- §3.7 Drafting — insert — ambiguity — requires `REMEDIATION_ACTIVE`, checked after the version check and before the supersede check — `routes/change_orders.py:34-41`
- §3.7 Decisions — insert — ambiguity — `decision_note` stored only when supplied; only approval requires a project state — `routes/change_orders.py:105-122`
- §3.8 Insurance notifications — insert — ambiguity — no project-state gate, and the new row participates in its own first waterfall run — `routes/insurance.py:29-40`
- §3.9 Claim filing — insert — ambiguity — no project-state gate, `claimed_costs_cents` an integer, duplicate check after the version check — `routes/claims.py:41-53`
- §3.9 Claim submit — insert — ambiguity — the disclosure-acknowledgment test precedes the eligibility test — `routes/claims.py:124-132`
- §3.9 Claim decision — insert — ambiguity — `DENIED` restores `unreimbursed_balance_cents`; `decision_note` stored only when supplied — `routes/claims.py:176-190`
- §3.9 NFA drafting — insert — ambiguity — `closing_date` is a full instant and drafting has no project-state gate — `routes/nfa_letters.py:26-37`
- §3.9 Rescission — insert — ambiguity — leaves `max_tph_mg_kg`/`max_benzene_mg_kg` and the disclosure latch standing — `routes/nfa_letters.py:111-115`
- §4 Endpoints — insert — ambiguity — undeclared paths yield `ERR_NOT_FOUND` (404) and undeclared methods `ERR_METHOD_NOT_ALLOWED` (405), neither listed in §5 — `app.py:54-63`

Constraints honored: only `PRD_COMPLETED.md` was written; no section added; no paragraph added; formulas/constants in `calculations.py` matched the PRD verbatim and needed no change; `SCAFFOLD*.yaml` and `worklog.md` were never opened; `test_suite/`/`test_helpers/` were used only as cross-reference and never as an alignment authority.

---

## Pipeline complete — 2026-09-01T16:08:31.337Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final artifact set present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/` (99 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` with `results.{1..8}.json` all green (99/99).

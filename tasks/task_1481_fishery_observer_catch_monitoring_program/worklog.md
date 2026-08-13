# Worklog — task_1481_fishery_observer_catch_monitoring_program

Scenario: Fishery Observer & Catch Monitoring Program (NOAA fisheries observer program): coverage requirement calculation & vessel selection, observer deployment logistics & sea-day scheduling, data collection protocol & sample verification, safety check of vessel before boarding, debriefing & data validation, harassment/interference reporting, cost recovery fee to industry, electronic monitoring alternative & video review

Difficulty target: HARDER THAN EXPERT LEVEL (user directive).

## Step 1: Create Task Directory — 2026-08-13T11:47:00.000Z

Task directory `tasks/task_1481_fishery_observer_catch_monitoring_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking pipeline. Step 1 treated as DONE per invocation args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold (completed on resume) — 2026-08-13T13:05:00.000Z

RESUME note: previous run was terminated after writing SCAFFOLD.yaml but before the two design files. On resume, SCAFFOLD.yaml verified complete (valid YAML, 1067 lines, all §1.1–§1.7 top-level keys present: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; NO scaffold_difficulty_design / scaffold_corner_design keys; clean EOF in roles section). SCAFFOLD.yaml kept as-is; a subagent generated only the two missing design files against it. Verbatim subagent summary:

Both design files are complete and verified. Final report:

## Summary

**Files written (exactly two, nothing else touched):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/SCAFFOLD_CORNER_DESIGN.yaml`      — single top-level key `scaffold_corner_design`

**§1.8 instance counts (21 active, all 9 rules ≥ 2, three rules carry a 3rd instance per the HARDER-THAN-EXPERT directive):**
- dual_variant_calc: 3 (CoveragePlan provisional/final; Invoice STANDARD vs SMALL_VESSEL — 413763 vs 206882 cents for identical 10-day patterns; EMTrip reviewed_pct vs catch extrapolation)
- combinatorial_formula: 2, in different modes — (b) per-line-then-sum rounding order (82752 vs non-conformant 82753) and (a) multi-input non-linear selection scoring with the conditional 1.25 gear branch (100.0000 vs 80.0000)
- non_linear_state_machine: 2 (HarassmentReport appeal cycle; Deployment revision loop + safety fork-join)
- transitive_cascade: 3 (delinquency depth-4; EM-activation depth-3; harassment-substantiation depth-2)
- priority_pair_validation_conflict: 2 (state>fiscal: ERR_INVOICE_NOT_ISSUED; referential>fiscal: ERR_OPERATOR_DELINQUENT)
- boundary_precision_check: 2 (EM reviewed_pct 0.2999/0.3000 on record-review; observer commitment cap 90-allowed/91-rejected on POST /deployments)
- cross_entity_state_dependency: 3 (CoveragePlan→Fishery; Deployment→VesselOperator; EMTrip→CoveragePlan)
- resource_temporal_overlap: 2 (observer closed-interval touching vs vessel full-day turnaround buffer)
- compensating_invariant: 2 (notice sea-day partition create-then-cancel; invoice balance identity via ISSUED→ISSUED compensating adjustments)

**§1.9 instance counts (71 total across all 9 guide sections: 52 active + 19 excluded_because stubs):** entities 11, state_machines 10 (5 active/5 stubs), calculations 7 (4/3), validations 10, endpoints 3, errors 16 (7/9), rbac 7, cross_cutting_layers 6 (4/2), consistency_model 1. Stubs cite covering §1.8/§1.9 instances by name; all stub references resolve.

**Verification:**
- All formula-derived assert literals were computed by executing the scaffold's own formulas in Python (coverage ceil with EM-share cap, selection scoring weights, tiered fee + 3.7% surcharge with pinned rounding order, fee-cap floor, sea-day accounting, EM threshold/extrapolation, sample coverage gates).
- Every `grounds:` entry resolves to a declared element in the existing SCAFFOLD.yaml (audited programmatically: calculations, transitions, validations by priority, error ids, entity fields, concurrency rule ids, roles, endpoints — 0 unresolved). Notably, replay caught that the scaffold declares waive only from ISSUED|DISPUTED|OVERDUE, so the invoice-invariant instance was reshaped to the declared ISSUED→ISSUED adjustment self-loop instead of inventing a PARTIALLY_PAID→WAIVED path.
- Placeholder closure: 0 unbound `${var}` across both files; OCC `expected_*_version` values always reference prior captures; opaque-role user ids pinned (`coord-user-1`/`admin-user-1`) wherever SoD comparisons need determinism.
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (91 endpoints, 16 entities, 21 + 52 active instances, 1115 calls scanned).
- Both files parse as valid YAML with exactly one top-level key each; 92 instance names are unique across the union; no forbidden concurrency vocabulary present.

## Step 3: Copy Shared Files — 2026-08-13T14:13:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T14:45:00.000Z

Verbatim subagent summary:

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/PRD.md` (~68 KB, ending at §5 with no audit footer).

## What was generated

A prose PRD for the Fishery Observer & Catch Monitoring Program API, built solely from `SCAFFOLD.yaml` and the doc-generator skill (the two `SCAFFOLD_*_DESIGN.yaml` files were never opened). Structure:

- **§1 Introduction** — 2 paragraphs (business context + system scope)
- **§2 Global Specifications** — 11 subsections: RBAC with per-role `identity:` prose (opaque `ProgramAdmin`/`ProgramCoordinator`; entity-backed `Observer`/`Debriefer`/`VesselOperator`/`EMReviewer`), the verbatim §2.2 envelope block (byte-verified against `section-2.2-response-structure.md`), pagination, common resource properties (with the `SafetyInspection` no-`updated_at`/no-`version` exception), left-to-right nested validation, precision/rounding conventions, logical clock + ops checkpoint, the three OCC rules, the sea-day ledger invariant, cascading reconciliation (delinquency / EM activation / harassment / auto-fulfillment), and the pinned 11-step validation ordering
- **§3 Business Logic** — 9 subsections (registries, coverage planning, selection scoring/notices, scheduling + safety gate, at-sea sampling/return, debriefing/close, harassment, EM, cost recovery) with all rules scattered as narrative; state pairs (`ISSUED → ACCEPTED`, etc.) used instead of paths
- **§4 Endpoint table** — all 91 endpoints, 4 columns each, plus the query-filter enumeration paragraph
- **§5 Error catalogue** — all 45 errors, 2 columns

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 146 required, 146 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.11 pinned order), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed (from/to, preconditions + error ids, side effects incl. all cascade hops), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (constants embedded: 40% EM cap, 30-day allocation, 50/30/10/5/1.25 scoring weights, 365-day recency window, 45-day max deployment, 90-day commitment cap, 20/30/45 certification caps, 39900/49900-cent tiers, 3.7% surcharge, 0.5% revenue cap, 30-day due window, 0.3000 review threshold, 0.2000 coverage gates), 0 missing
- validations[] conditions: 45 error ids checked, 45 matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, nullability (e.g. reviewed_pct/estimated_total_catch_kg/final_*_sea_days null-until), derived fields reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (PASS/FAIL, accept/decline, partial/full payment ×3 payable states, adjustments ×3 states, waive ×3 states, terminate ×2 states, decertify ×2 states, PROVISIONAL/FINAL, STANDARD/SMALL_VESSEL), all equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 605
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One verification note: my tokenizer initially mis-paired backticks around the §2.2 fenced JSON blocks (false "missing field" alarms); stripping fenced blocks before extraction confirmed true full coverage. The single enum-check flag (`EME`) is a regex artifact from the word "EMEnrollment" in scaffold prose, not a real enum value.

## Step 5: Generate Unit Tests — 2026-08-13T16:10:00.000Z

Verbatim subagent summary:

Generation complete. **93 tests across 9 files, all audits green.**

## What was generated

**`test_helpers/`** (Stage 1) — under `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/test_helpers/`:
- `types.py` — all 16 entity TypedDicts + status/role enums; `SafetyInspection` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~70 endpoints)
- `api_errors.py` — all 46 error IDs with HTTP statuses, registered via `set_error_http_status_map` (plain string keys)
- `constants.py`, `factories.py`, `test_users.py` (with mandatory `make_<role>_headers` per-instance builders for the four entity-backed roles), `assertions.py` (per-entity + notice sea-day partition and invoice balance invariant checkers)
- `fixtures.py` — tiered composite fixtures: notice scenario, full deployment lifecycle to DATA_VALIDATED/CLOSED, issued-invoice, delinquency-cascade, harassment-under-review, EM-active vessel, EM trip in review, two-vessel billed scenario

**`test_suite/`** (Stage 2) — 93 tests, each with a verbatim PRD citation and exactly one terminal `Design:` tag:
- Queue A: all **21/21 difficulty instances** covered by exactly ≥2 tests each
- Queue B: **51/52 non-stub corner instances** covered; all `excluded_because:` stubs verified to resolve and not translated

## Skips and adjudications (PRD-first filter)

1. **Skipped entirely**: `Corner/validations/vessel_not_active_and_observer_not_available_and_em_mode_gates` — both legs present dual violations within the same validation priority (vessel-mode vs enrollment-active, both priority 9), so the asserted error is not uniquely derivable from the PRD. Gap left as a gap.
2. **`sample_coverage_gate_layered_failures`**: translated gates 1–2 only; the gate-3 leg is unreachable because intake rejects any sample with ratio < 0.2000, making a 0.1980 verified-coverage case impossible to construct.
3. **`occ_invoice_adjustment_stale_version`**: restructured the version-bumper from payment to a prior adjustment — the recipe's payment leaves the invoice PARTIALLY_PAID, from which PRD §3.9 does not permit adjustments, so the "retry succeeds" leg would be unreachable as written.
4. **`invoice_generate_skips_vessel_with_existing_open_invoice`**: asserted `skipped_vessel_ids` and the untouched open invoice; omitted the `created_invoice_ids == []` claim because whether already-billed CLOSED deployments are re-billable is not pinned by the PRD.
5. **`fishery_creation_applies_defaults`**: omitted `version == 1` (initial counter value not pinned); kept status/uuid/created_at-at-startup-clock assertions.

## Verification performed
- All files compile; `pytest --collect-only` collects 93 tests cleanly with `test_helpers` importable
- Coverage audit: every test has exactly one tag as its docstring's last line; every tag resolves to a real instance; no untagged/dual-tagged tests
- All 108 quoted PRD citations verified verbatim against `PRD.md` (whitespace-normalized grep)
- All pinned numeric literals (210/360 coverage, 413763/206882/41376/82752 fees, 100000 cap, 301.25 extrapolation, 100.0/80.0 scores, all day counts) verified with exact Decimal arithmetic
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold/table references in generated code comments

## Step 6: Generate Implementation — 2026-08-13T16:10:00.000Z

Verbatim subagent summary:

Implementation complete. All four smoke/edge suites pass against a fresh `start.sh` boot.

## What was built

A complete Python + Flask implementation of the Fishery Observer & Catch Monitoring Program API at `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/implementation/`:

- `start.sh` — guarded dependency install (no-op once Flask is importable), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts only, **zero seeding**; logical clock starting at exactly `2026-08-01T00:00:00Z`, never wall-clock
- `core.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), error body (`error_id`/`message`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, 1–100), auth on `X-User-ID`/`X-User-Role` with entity-backed role resolution and SUSPENDED→403, field/parsing/Decimal helpers
- `logic.py` — coverage requirement (pinned 4-step EM-cap/ceil calc, live fishery target), selection scoring (recency/compliance/penalty, 1.25 gear multiplier, score DESC → last_observed_end ASC NULLS FIRST → created_at ASC, never id), sea-day ledger (invariant `allocated = remaining + reserved + consumed`), delinquency/EM-activation/harassment cascades, cumulative-tier invoice generation with per-line round-half-up then sum, revenue floor cap
- Route modules for registries, plans/runs/notices, deployments/safety/samples, harassment, EM, billing/ops/clock

## Key fidelity decisions (from PRD over scaffold where they diverged)

- Validation priority follows PRD §2.11 exactly: auth → authz → existence → schema → OCC (412) → state → safety → temporal → referential → caps → fiscal; so e.g. a stale notice version beats `ERR_NOTICE_NOT_ACCEPTED`, and `ERR_DATE_RANGE_INVALID`/`ERR_VESSEL_TURNAROUND_VIOLATION` precede vessel-mode/operator-standing checks
- Vessel turnaround uses the literal formula `(new_departure − existing_return).days − 1 >= 1` against every active deployment of the vessel
- Every mutation (including system cascades) refreshes `updated_at` and bumps `version` per PRD §2.4/§2.10; SafetyInspection carries only `id`/`created_at`
- Input date strings are echoed verbatim; clock-derived datetimes (`submitted_at`, `issue_date`, `due_date`, early-termination `actual_return_date`) use the canonical clock format (`...Z`, no fraction on whole seconds)
- Decline has no deadline check; accept requires `clock <= response_deadline`; ops run expires only strictly-past deadlines
- EM reactivation from SUSPENDED performs no cascade; harassment dismissal refunds the 3-point penalty only when `penalty_applied` was true

## Verification

Four test scripts exercised: full happy path (registry → plan → publish → selection → accept → deployment → safety gate incl. supersession → board → samples → return → debrief → validate → close → invoice → issue → payments → overdue cascade → standing restore), scoring/ranking/backfill runs, all deployment screens (caps, overlap, turnaround, allocation, OCC), harassment early-termination arithmetic with clock clamp, EM enrollment cascade voiding notices + cancelling deployments with day release, EM review 0.2999/0.3000 threshold, trip accept catch extrapolation (12×100/30=40.0) and plan EM-day credit, plan-close FINAL calc + attainment (30/60=0.5) + DEFAULTED +2 penalty, invoice tier crossover (20-day boundary), SMALL_VESSEL 0.5 factor, revenue cap with `fee_cap_applied`, waiver adjustment math, pagination meta, and auth/existence error envelopes on every endpoint family.

## Step 7: Run Tests and Iterate — 2026-08-13T16:45:00.000Z

Verbatim subagent summary:

## Summary

**Exit condition met: all 8 parallel rounds pass 93/93 (passed == total in every round, zero failures, zero errors).**

- **Iterations run:** 2 sweeps (iteration 1: 4 deterministic failures in all 8 rounds; iteration 2 after fixes: 8/8 rounds fully green).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`** (both were STEP 2 test bugs — the test issued a request a PRD-faithful implementation must reject):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/test_suite/test_05_return_debrief_close.py` — `test_sample_gates_unresolved_then_zero_verified`: the test recorded its second haul sample after the deployment had returned (DEBRIEFING), violating PRD §3.5 verbatim ("While the deployment is `AT_SEA` — and only then, attempts in any other status drawing `ERR_INVALID_STATE`"). Restructured the setup so both samples are recorded while AT_SEA; the PRD §3.6 gate-1 (`ERR_SAMPLES_NOT_RESOLVED`) and gate-2 (`ERR_SAMPLE_COVERAGE_INSUFFICIENT`) assertions are unchanged.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/test_suite/test_09_coverage_and_invoices.py` — `_setup_two_single_day_invoice` (used by `test_per_line_rounding` and `test_sum_of_rounded_lines_not_rounded_sum`): the two 1-day deployments used identical departure and return timestamps, violating PRD §3.4 verbatim ("The return date must fall after the departure, else `ERR_DATE_RANGE_INVALID`"). Changed each to depart 00:00 and return 12:00 the same calendar day (inclusive day count still 1), preserving the pinned §3.9 rounding assertions (line_total 41376 each, amount_due 82752, not the sum-then-round 82753).

- **Fixes applied to `implementation/`** (STEP 3 — test faithful, PRD covers the rule):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/implementation/store.py` — `new_entity`, `new_inspection`, `touch`: `created_at`/`updated_at` now stamp from the logical clock (`fmt_ts(clock_now())`, always three fractional digits per §2.4) instead of wall-clock. Required by PRD §2.7 verbatim ("The program runs on a logical clock rather than wall-clock time … it must never fall back to wall-clock time") composed with §2.4's "created_at … recording when the resource was created"; fixes `test_fishery_creation_applies_defaults` (created_at == `2026-08-01T00:00:00Z` at startup).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/implementation/core.py` — `_meta()`: `api_request_timestamp` also reads the logical clock for the same §2.7 reason (no test pins its value; consistency fix).

No implementation checks were weakened, no endpoints/fields added beyond PRD, no tests skipped or assertions downgraded.

## Step 8: Finalize PRD — 2026-08-13T17:05:00.000Z

Verbatim subagent summary:

Both edits are applied. Here is the exit summary.

## Summary

**Line counts:** `PRD.md` 404 lines, `PRD_FINALIZED.md` 404 lines — 0.00% line delta (two bullets revised inline, one extended; no lines added or removed, no new sections).

**Changes (one bullet per edit):**

- **§2.2 — revise** — the `api_request_timestamp` bullet now reads "...with three fractional digits, read from the logical clock of §2.7 rather than wall-clock time." — `implementation/core.py:65` (sole producer `_meta()`, `store.fmt_ts(store.clock_now())`, feeding both `ok()` and `err_response()`).
- **§2.4 — revise** — the `created_at` bullet now pins "read from the logical clock of §2.7 — a resource created before the clock is first advanced therefore carries `2026-08-01T00:00:00.000Z`, never a wall-clock reading", and the `updated_at` bullet gains "with three fractional digits" plus "likewise read from the logical clock of §2.7 rather than wall-clock time." — `implementation/store.py:97-99` (`new_entity`), `store.py:109` (`new_inspection`), `store.py:116` (`touch`); all render via `fmt_ts(clock_now())`.

**Step-7 items that produced no PRD edit:** the two `test_suite/` fixes were pure fixture bugs — the tests violated verbatim PRD text that already uniquely determines the behavior (§3.5's "While the deployment is `AT_SEA` — and only then" in `test_05_return_debrief_close.py`; §3.4's "The return date must fall after the departure, else `ERR_DATE_RANGE_INVALID`" in `test_09_coverage_and_invoices.py`). PRD prose kept verbatim per method rule 2.

**Per-edit pre-edit search log:**

1. **Edit §2.4 (`created_at`/`updated_at` clock source + 3-fractional-digit rendering of `updated_at`)**
   - (a) Subject: which clock stamps the §2.4 system-managed timestamps, and `updated_at`'s fractional-digit rendering.
   - (b) Enumerated paths (grep for `"created_at"]`, `"updated_at"]`, `new_entity(`, `new_inspection(`, `touch(` across all of `implementation/`): writes occur in exactly three places — `store.py:97-99`, `store.py:109`, `store.py:116`, all `fmt_ts(clock_now())`; every creation route (`routes_registries.py:50,108,163,246,313`; `routes_plans.py:47,195,207`; `routes_deployments.py:93,394,472`; `routes_harassment.py:27`; `routes_em.py:47,195`; `logic.py:383`) funnels through those helpers, as does every one of the ~50 `store.touch()` mutation sites across `logic.py`, `routes_billing.py`, `routes_deployments.py`, `routes_em.py`, `routes_harassment.py`, `routes_plans.py`, `routes_registries.py`. Remaining `created_at` hits are read-only sort keys (`core.py:343`, `logic.py:128,271,280,332,347`, `routes_billing.py:214,227`, `routes_plans.py:136,237`, `routes_deployments.py:388`). `now_wall()` (`store.py:65-66`) is defined but never called — no wall-clock path exists. Also verified the sibling server-stamped fields already pinned by PRD narratives: `submitted_at` (`routes_deployments.py:244`, pinned by §3.6), `issue_date`/`due_date` (`routes_billing.py:73-74`, pinned by §3.9), early-termination `actual_return_date` (`logic.py:292`, pinned by §3.5), `current_utc` (`routes_billing.py:245`, pinned by §2.7) — all read `clock_now()`, so "logical clock" wording is consistent with every timestamp the server emits; the safety-inspection exception (§2.4) inherits the revised `created_at` bullet correctly via `new_inspection`.
   - (c) Wording adjustment: added "with three fractional digits" to the `updated_at` bullet (previously unstated there) only after confirming both write sites use `fmt_ts`, which always renders three fractional digits; used scoped "read from the logical clock of §2.7" phrasing rather than a universal "every timestamp" claim to stay under-determined off the enumerated sites.

2. **Edit §2.2 (`api_request_timestamp` clock source)**
   - (a) Subject: which clock stamps the response-envelope `api_request_timestamp`.
   - (b) Enumerated paths (grep for `api_request_timestamp`, `_meta`): sole producer is `core.py:61-66` `_meta()`, which reads `store.fmt_ts(store.clock_now())` and is consumed by `ok()` (`core.py:80`), `ok_list()` (`core.py:89`), and `err_response()` (`core.py:95`) — i.e., every success and error envelope. No other producer exists.
   - (c) Wording adjustment: none — appended the same scoped clause; the bullet's existing "three fractional digits" already matches `fmt_ts`, and the clause holds for both success and error envelopes since both share `_meta()`.

Result: a fresh implementer reading `PRD_FINALIZED.md` now has the clock source for `created_at`/`updated_at`/`api_request_timestamp` pinned explicitly — closing the exact gap that drove the original implementation to wall-clock and caused the `test_fishery_creation_applies_defaults` failure — with all other PRD prose untouched.

## Step 9: Complete PRD — 2026-08-13T17:45:00.000Z

Verbatim subagent summary:

All edits verified against the implementation. Final state: PRD_COMPLETED.md is 404 lines (unchanged line count — all changes are in-paragraph inserts/revisions), 73,070 chars vs 69,215 (+3,855).

## Summary

**Source:** `PRD_FINALIZED.md` (404 lines) → `PRD_COMPLETED.md` (404 lines, +3,855 chars). All changes are inline inserts/revisions within existing paragraphs; no new sections, no invented behavior.

**Counts:** 30 ambiguity-pins (inserts), 2 ambiguity-revisions (loose wording re-pinned), 1 mismatch-revision.

### Ambiguity-pins (insert)

- §2.5 — insert — ambiguity — undefined path or unsupported method on a defined path → `ERR_NOT_FOUND` 404 — app.py:39-46
- §2.5 — insert — ambiguity — body references resolved only when string-typed; wrong type falls to schema step — routes_plans.py:28-34, routes_registries.py:142-144
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — core.py:306-331
- §2.3 — insert — ambiguity — `created_at` ties broken by creation order; `has_more` true iff records remain past the page — core.py:343-351
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — store.py:100
- §2.6 — insert — ambiguity — two-decimal request fields (`sampled_weight_kg`, `total_haul_weight_kg`, `video_hours`) reject >2dp input with `ERR_INVALID_REQUEST`, never rounded — core.py:285-291
- §2.6 — insert — ambiguity — ISO 8601 input parsing: date-only → UTC midnight; offset-less datetime → UTC — core.py:234-250
- §2.7 — insert — ambiguity — clock endpoint accepts any parseable instant, earlier or later — routes_billing.py:236-245
- §2.7 — insert — ambiguity — clock-derived readings (`current_utc`, `issue_date`, `due_date`, `submitted_at`, early-termination `actual_return_date`) render 3 fractional digits, dropped on whole seconds — store.py:75-82
- §2.7 — insert — ambiguity — `delinquent_operator_count` counts operators newly turned DELINQUENT (no recount within a sweep) — logic.py:226-229
- §2.11 — insert — ambiguity — step 4 covers non-object body, empty required strings, bool-as-number; unknown fields ignored — core.py:146-231
- §3.1 — insert — ambiguity — vessel activation/reactivation with non-ACTIVE operator, and out-of-set transitions, → `ERR_INVALID_STATE` — routes_registries.py:207-217
- §3.1 — insert — ambiguity — observer PATCH amends `home_port` and `certification_level` alongside status — routes_registries.py:292-297
- §3.1 — insert — ambiguity — re-submitting current status on any registry PATCH is a no-op success that still refreshes `updated_at`/bumps `version` — routes_registries.py:82-91,207-227,277-298,320-328
- §3.3 — insert — ambiguity — recency day count not floored at zero (negative component possible) — logic.py:74-79
- §3.3 — insert — ambiguity — ranking tie on `created_at` resolves in creation order — logic.py:119-129
- §3.3 — insert — ambiguity — `vessels_evaluated` = number of eligible vessels scored — routes_plans.py:186,199
- §3.3 — insert — ambiguity — declining a notice does not consult the response deadline — routes_plans.py:296-305
- §3.6 — insert — ambiguity — debriefer assignment allowed in any non-terminal status; CLOSED/CANCELLED → `ERR_INVALID_STATE` — routes_deployments.py:264-265
- §3.6 — insert — ambiguity — resubmission from DATA_REJECTED does not re-check the ≥1-sample floor — routes_deployments.py:240-241
- §3.6 — insert — ambiguity — sample verify/flag/discard by anyone but the assigned debriefer (including none assigned) → `ERR_FORBIDDEN` — routes_deployments.py:504-511
- §3.7 — insert — ambiguity — harassment report may be filed whatever the deployment's status — routes_harassment.py:17-39
- §3.8 — insert — ambiguity — EM enrollment does not consult the vessel's registry status — routes_em.py:29-56
- §3.8 — insert — ambiguity — EM trip declaration likewise ignores vessel registry status — routes_em.py:150-210
- §3.8 — insert — ambiguity — assigning a non-ACTIVE EM reviewer → `ERR_INVALID_STATE` — routes_em.py:262-263
- §3.8 — insert — ambiguity — review batches require positive hours / non-negative catch delta (else `ERR_INVALID_REQUEST`), accepted at any precision, accumulated unrounded — routes_em.py:277-290
- §3.8 — insert — ambiguity — accepting a terminal (ACCEPTED/REJECTED) trip → `ERR_INVALID_STATE` — routes_em.py:301-302
- §3.9 — insert — ambiguity — `created_invoice_ids` ordered by billed vessels' `created_at` ascending — logic.py:331-333
- §4 — insert — ambiguity — list filters are exact equality matches — core.py:334-343

### Ambiguity-revisions (reword)

- §3.5 — revise — ambiguity — early-termination `actual_return_date`: "current clock date" → "the clock's current reading" (full timestamp) — logic.py:292
- §3.9 — revise — ambiguity — `issue_date` = clock's current reading; `due_date` exactly thirty 24-hour spans later — routes_billing.py:71-74

### Mismatch-revisions

- §3.2 — revise — mismatch — `coverage_attainment_pct` is zero whenever `final_required_observer_sea_days` is zero (PRD said "when both figures are zero", which mismatches impl when the requirement is 0 but observer days are positive) — routes_plans.py:122-124

File: `/home/ubuntu/github/CodingPRD/tasks/task_1481_fishery_observer_catch_monitoring_program/workspace/PRD_COMPLETED.md`

PIPELINE COMPLETE: all 9 steps done; final 8-round sweep 93/93 green; PRD_COMPLETED.md exists.

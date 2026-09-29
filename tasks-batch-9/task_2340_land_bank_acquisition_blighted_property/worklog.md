# Worklog — task_2340_land_bank_acquisition_blighted_property

## Step 1: Create Task Directory — 2026-09-01T20:31:05.319Z

Created `tasks/task_2340_land_bank_acquisition_blighted_property/` and `tasks/task_2340_land_bank_acquisition_blighted_property/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T22:20:55.471Z

All three artifacts are complete and the linter is clean.

Verdict block, verbatim from `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2340_land_bank_acquisition_blighted_property`:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  965

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Final fixes applied this pass: normalized every §1.5 path parameter to `{id}` across all three files (satisfies the linter's sub-resource reverse-reachability form for `TitleAction.property_id`, `DemolitionRun.funding_source_id`, `ParcelAdjacency.property_id`/`adjacent_property_id`, `ReuseHearing.property_id`, `EligibilityScreening.application_id`, and matches the `{id}` convention already used in the prose); corrected `milestones_completed_count` → `milestones_completed` (real §1.1 field, 3 sites); moved the Applicant-field captures (`open_code_violation_total`, `eligibility_status`) off the Property-returning `owner-of-record` call onto a new `GET /land-bank/applicants/${appl_bad_id}` call.

Files (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/SCAFFOLD_CORNER_DESIGN.yaml`

Scaffold contents (§1.0–§1.7), calibrated above expert level:
- Profile: `api_prefix: /land-bank`, primary archetype Compliance/audit + secondary Quota/allocation, layers `cascading_side_effects, dual_variant_calculation, optimistic_concurrency, selector_policy, ops_run_checkpoint`, topology `graph`, SM shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.
- 13 entities: Property, FundingSource, AcquisitionPacket, TitleAction, Contractor, MaintenanceOrder, DemolitionRun, Applicant, ParcelAdjacency, ReuseHearing, DispositionApplication, EligibilityScreening, DevelopmentAgreement (4 immutable, `common_fields: false`).
- 9 state machines (parallel Property custody × title dimensions, cyclic application INFO_REQUESTED/SUSPENDED_TITLE loops, agreement CURE_PENDING → COMPLIED | REVERTED with custody reverter back to LISTED), 2 §1.2.1 concurrency rules (property version on maintenance-order create, funding-source version on demolition-run create).
- 9 calculations (dual-variant blight score INTAKE_PROVISIONAL vs SWEEP_FINAL, dual-variant tax discharge STATUTORY vs NEGOTIATED, tiered side-lot pricing with assessed cap, two-stage demolition estimate, run budget cap + admin fee, reserve-floor availability with ceiling, hearing support ratio, disposition price by program with floors and structure discount, inventory/ledger rollup).
- 48 ordered validations (priorities 10→98), 52 endpoints, 59 errors (every one triggered by at least one design instance), 6 roles including an `entity_backed:Applicant` role.

Design instance counts:
- §1.8 difficulty: 9 rule blocks / 19 instances — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.
- §1.9 corner: 85 instances (72 with test recipes, 13 `excluded_because` stubs) — entities 12, state_machines 14, calculations 15, validations 23, endpoints 7, errors 3, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1.
- All 104 instance names are unique across both design files.

## Step 3: Copy Shared Files — 2026-09-01T22:20:55.471Z

Copied `INSTRUCTION.md` → `tasks/task_2340_land_bank_acquisition_blighted_property/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T23:00:13.277Z

PRD generated and all three Hard Contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/workspace/PRD.md` — 417 lines, 27 headings.

**Sections:** §1 Introduction; §2 Global Specifications (2.1 RBAC over the six roles, 2.2 API Response Structure pasted verbatim from `section-2.2-response-structure.md`, 2.3 Pagination + the four declared per-list orderings + list filters, 2.4 Resource identity/timestamps/`version` and the logical clock, 2.5 left-to-right path and body-reference resolution, 2.6 the parallel `custody_status` × `title_status` dimensions, 2.7 money/scores/pinned rounding, 2.8 the conserved funding ledger and reserve floor, 2.9 OCC on parcels and funding sources, 2.10 segregation of duties, 2.11 conserved inventory area, 2.12 the 13-step validation precedence ladder); §3 Business Logic in 9 narrative subsections (registry → funding → acquisition → title → maintenance → blight/demolition runs → listing/hearings/pricing → screening/recommendation/board → conveyance/reverter/sweep); §4 the 52-row endpoint table; §5 the 59-row error catalogue. No audit footer in the file.

Coverage audit (all mechanically diffed against `SCAFFOLD.yaml` with a Python/YAML script, not by eye):

```
Field coverage check:
- entities[].fields: 136 required, 136 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 48 checked, 48 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_property_version / expected_funding_source_version + ERR_STALE_*_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (all constants, pinned rounding/evaluation orders, both variant pairs), 0 missing
- validations[] conditions: 48 checked, 48 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 88 side-effect bullets + 48 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 136 checked, 136 reconstructible from prose (all enum literals verified present), 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 746
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Cross-checks beyond the contracts: all 52 endpoint paths present with role lists matching `endpoints[].roles` exactly (0 diffs), all 59 error IDs present with HTTP statuses matching `errors[].http` exactly (0 mismatches), §2.2 byte-identical to the source block.

Three internal scaffold contradictions were resolved and the choices are stated explicitly in the prose: (a) `delinquent_tax_balance_cents` is **not** zeroed at acquisition close — only frozen into `pre_acquisition_delinquency_cents` — because the field description, the custody transition table and the discharge/reverter calculations all require a live balance for the discharge to debit and the reverter to restore, whereas only the endpoint's side-effect bullet said otherwise; (b) `SUSPENDED_TITLE` exits only via the title-clearing restore to `suspended_from_status`, per the state machine, not via resubmit; (c) recommending against a non-`CLEAR` title rejects with `ERR_TITLE_NOT_CLEAR` per validation priority 63 rather than silently suspending. `ERR_TITLE_NOT_CLEAR` was deliberately *not* extended to agreement execution (outside its declared `applies_to`); that precondition is stated as a consequence of the listing rule instead.

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced, and no sibling task directory under `/home/ubuntu/github/CodingPRD/tasks/` was read.

## Step 5: Generate Unit Tests — 2026-09-01T23:38:41.471Z

Test generation is complete for `task_2340_land_bank_acquisition_blighted_property`.

## Files written

**Stage 1 — `test_helpers/` (9 files)**
`constants.py` (every calculation rate, weight, cap, threshold), `types.py` (role constants, all enum tuples, TypedDicts for the 10 common-field entities and the 3 append-only journal rows), `api_errors.py` (`ApiErrorId` with all 59 IDs + `HTTP_STATUS_CODES` registered with the framework's validators), `test_users.py` (staff header constants + `make_applicant_headers`), `api_client.py` (`ApiClient` with one method per declared endpoint), `factories.py` (payload factories with sequential parcel-ID minting), `assertions.py` (`round_half_up`, the `expected_*` cost calculators, per-entity shape checkers, ledger/inventory invariant checkers), `fixtures.py` (5-tier composite state builders), `__init__.py` (barrel).

**Stage 2 — `test_suite/` (conftest + 23 test files, 162 tests)**
`test_01`–`test_09` = queue A; `test_10`–`test_23` = queue B.

## Test counts

| Queue | Instances | Non-stub | Covered | Tests |
|---|---|---|---|---|
| A — Difficulty (§1.8) | 19 across 9 rule_ids | 19 (no stubs) | **19/19**, every one with ≥2 tests | 48 |
| B — Corner (§1.9) | 85 across 9 sections | 72 (13 stubs) | **72/72**, every one with ≥1 test | 114 |

## Verification passed

- 162 tests collect cleanly; all files compile.
- **162 `Design:` tags = 162 tests** — no untagged, no dual-tagged test; every tag resolves to a real `name:` in the source yaml under the section it claims; every tag is the last line of its docstring.
- All 13 `excluded_because:` stubs untranslated — none of their names appears anywhere in the suite.
- Every one of the 162 docstrings contains a PRD span verified verbatim against `workspace/PRD.md`.
- No `skip`/`xfail`/mocking/monkeypatching; no raw envelope access (all assertions go through the framework validators); no imports from `workspace/implementation/` or any sibling task.
- `test_helpers/` mtimes all predate the first test file — no worker mutated Stage 1.

## Instances skipped

**None.** Every non-stub instance in both indices had verbatim PRD backing that uniquely derived its outcome.

## Key findings worth your attention

1. **The corner design's ledger arithmetic is wrong in ~5 places.** It computes `available_cents` as `authorized − committed − disbursed − reserve_floor`. The PRD states plainly: `available_cents is authorized_cents less committed_cents less disbursed_cents`, and the reserve floor is a *status threshold*, not a deduction. Four workers independently hit this and followed the PRD; I confirmed it directly. Affected values were re-derived (e.g. 991000 not 941000; 980297 not 930297; 800000 not 750000).
2. **Several recipes use out-of-domain literals** that would trip shape validation before the rule under test: `situs_ward` / `situs_ward_filter` values of 11, 12, 41, 42, 44 (PRD range is 1–9), and `restriction: MAINTENANCE_ONLY` (not a PRD enum). Substituted with in-range values preserving each instance's distinguishing point.
3. **Two corner instances had internally inconsistent pinned scores** — `property_get_returns_stored_registry_fields` asserts 37.5 while its own term breakdown sums to 41.0, and `property_acquisition_fields_computed_at_packet_close` pins a grade-C structure term on a parcel declared `structure_present: false`. PRD-derived values were used.
4. **`board_approval_on_constrained_source_rejected`** as written would return `ERR_PACKET_INVALID_STATE`, not `ERR_FUNDING_CONSTRAINED`, because the PRD's ordering ladder checks the packet's from-state before fiscal capacity. Setup was reordered so the intended error is the unique outcome.
5. **Three individual assertions were dropped** (instances still covered) as not PRD-derivable: `suspended_from_status == SCREENED` on request-info (PRD implies `SUBMITTED`), `conveyed_property_count == 1` after a reverter (PRD supports both 0 and 1), and `tier_applied` literals (PRD pins no values).

## Step 6: Generate Implementation — 2026-09-01T23:38:41.471Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` (executable) | launcher: `cd` to script dir, guarded `pip install -r requirements.txt` only if flask missing, `exec python3 app.py` (honours `$PORT`, default 10000) |
| `requirements.txt` | `flask>=3.0.0` |
| `app.py` | Flask app, `strict_slashes=False`, per-request `RLock` + `g._touched` reset, `ApiError`/`HTTPException`/`Exception` handlers, `register_routes` |
| `db.py` | in-memory `Store` (13 dicts + `_seq` + logical clock), `now/new_id/base_record/touch/ordered`; **no seeding** |
| `clock.py` | logical UTC clock (default `2026-08-01T00:00:00Z`), ISO-8601 with exactly 3 fractional digits |
| `response.py` | `{meta,response_type,data}` envelopes; `req_` + 20 uppercase alnum request ids |
| `errors.py` | 60 domain error ids → status map, `ApiError`, `bad_request` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth, 6 roles, 401 before 403 |
| `validation.py` | body/field/enum/datetime coercion, pagination (limit 1..100 default 10, offset ≥ 0), query filters |
| `calculations.py` | all pinned constants + `Decimal`/ROUND_HALF_UP formulas: blight score, order estimates, demolition estimate, price quotes, tax discharge/abatement, hearing support, reserve floor, eligibility score |
| `serializers.py` | explicit field lists per entity; append-only entities expose only `id`/`created_at` |
| `services.py` | domain engine: ledger recompute + reserve-floor parking, blight refresh, applicant rollup/eligibility, submit-gate and screening ladders in pinned order, run allocation (floor provisional cap, skip-over walk, 5-parcel ceiling, admin fee after walk), 3-step compliance sweep with 4-link reverter chain, inventory summary |
| `routes/{__init__,properties,funding,maintenance,disposition,ops}.py` | HTTP layer |

## Endpoints
All 52 rows of PRD §4 are registered (verified by diffing the PRD table against `app.url_map`: 52 PRD rows vs 52 registered rules excluding Flask's `/static`): properties + code-violation/tax-roll/owner-of-record/list/price-quote, title actions + adjudicate, reuse hearings, parcel adjacencies, funding sources + nested runs + TIF recapture, acquisition packets + board-approval/close/decline, contractors, maintenance orders + complete/cancel, demolition runs + execute, applicants, disposition applications + submit/screen/screenings/request-info/resubmit/recommend/board-decision, development agreements + milestone-completions, compliance sweeps, inventory summary, `POST /_clock/set_current_utc`. Every declared list filter from PRD §2.3 is implemented.

## Boot verification
- `python3 -m compileall` clean; fresh `bash start.sh` boots in ~2 s and serves immediately.
- Fresh-process store is empty: `GET /land-bank/properties` → `total_count: 0`, `data: []`; summary all zeros — no seeded data anywhere.
- End-to-end smoke suite (~130 assertions, `/tmp/smoke_lb.py`) passes with **0 failures** against a freshly booted process, covering: envelope/meta shape, 401-before-403 RBAC, parcel registration + duplicate/format rejection, blight recompute and version bumps, funding authorization with 5 % reserve floor, packet approve/close with segregation of duties (403 on same officer), ledger identity `authorized = available + committed + disbursed` held at every step, title action round/adjudication and CLEAR transition, OCC 412 on both `expected_property_version` and `expected_funding_source_version`, MOW estimate 15762, window-conflict 409, price quote 3060000 (assessed cap 3600000 + 15 % condition discount), application submit/screen/recommend (dual-control)/board-decision, agreement discharge 250000 + abatement 56800/284000, conveyance cascade (owner-of-record, delinquency discharge, inventory→conveyed area), demolition run cap 4651162 / subtotal 1661357 / admin fee 124602 / execute → one order, empty-run and re-execute guards, compliance sweep cure-pending → reverter (custody REVERTED, title CLOUDED, owner cleared, applicant BARRED, 5200 sqft restored) → funding EXPIRED, pagination bounds and `ERR_PROPERTY_NOT_FOUND`.
- Two initial smoke mismatches were test-data errors on my side (a candidate parcel scoring 36 < the PRD's 40 blight threshold), confirmed correct in the implementation against PRD line 240; no code changes were needed.
- All test servers were shut down; ports 10731/10732 are free and `__pycache__` was removed.

## Step 7: Run Tests and Iterate — 2026-09-02T06:57:53.877Z

All 8 rounds are green. Final sweep (results files in `workspace/implementation/results.1..8.json`): each round `total 162, passed 162, failed 0, errors 0`.

## Summary

**Iterations run:** 1 diagnostic iteration (one class of real failure found and fixed), followed by repeated stability sweeps until 8/8 rounds were clean. Most wall-clock time went to host contention, not to artifact defects (details below).

**Tests deleted:** none. No test was PRD-silent or non-derivable in a way that required deletion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/test_helpers/assertions.py` — added `from datetime import datetime` and a new `assert_same_instant(actual, expected)` helper that asserts two ISO-8601 UTC strings name the same *instant* (still requires a valid ISO-8601 UTC timestamp and non-null).
- `test_helpers/__init__.py` — re-exported `assert_same_instant`.

**Fixes applied to `test_suite/` (STEP 1c partial-coverage split, 17 call sites):**
- `test_03_state_machine_cycles.py` (6), `test_04_transitive_cascades.py` (7), `test_08_resource_overlap.py` (4) previously compared *business* instants (`listed_at`, `cure_deadline`, `reverted_at`, `last_reverter_at`, `swept_at`, `executed_at`, `window_start`, `window_end`) by exact string against literals like `2026-09-05T00:00:00Z`, while the implementation renders `2026-09-05T00:00:00.000Z`. PRD §2.4 pins the three-fractional-digit rendering only for `created_at`, `updated_at` and `meta.api_request_timestamp`; it is silent on how business instants are spelled (format silence). The PRD-covered part — *which instant* is stamped — is kept and still asserted exactly; only the non-derivable spelling was dropped. `test_13_state_guards.py:271` was deliberately left as an exact comparison because it compares a response value to an earlier response value.

**Fixes applied to `implementation/`:** none. No endpoint, field, side effect or seeded data was touched; storage remains in-memory.

**Environment findings worth relaying (not artifact defects):**
- The shared host was saturated by ~10 other tasks' concurrent sweeps (load 200–400 on 32 cores, ~300 `prd-bench-local-run` processes, ~140 concurrent `lsof`). The runner's per-test port cleanup (`lsof -ti:PORT -sTCP:LISTEN` under a hard 5 s timeout in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py::_kill_port`) then raises `subprocess.TimeoutExpired` during pytest setup, which the runner records as a per-test **error**. An early full sweep showed 71–91 such errors per round with **0 failures**; every one of the 162 tests passed in at least one round or under isolated re-run. I worked around this with a load-gated, fail-fast retry driver rather than changing the shared runner.
- Long-running processes were repeatedly SIGKILLed from outside (no kernel OOM records); other agents' broad `pkill -f "sweep.sh"` / `pkill -f prd-bench` patterns match cross-task processes, so a uniquely named single-process driver was needed to finish a sweep.
- One round initially showed a single `failed`: `test_19_validation_gates_program.py::test_community_use_by_an_individual_is_refused_on_the_pairing_rule` with `ConnectionResetError(104)` — a transport-level death of that test's server, no assertion involved. It passed 15/15 in isolated fresh-server reruns and in all other rounds; the re-run of that round came back 162/162.

Scaffolding I created during triage has been removed from the task directory (only `test_helpers/`, `test_suite/`, `workspace/`, the SCAFFOLD files and `worklog.md` remain, plus the 8 mandated results files).

## Step 8: Finalize PRD — 2026-09-02T07:00:54.757Z

`/home/ubuntu/github/CodingPRD/tasks/task_2340_land_bank_acquisition_blighted_property/workspace/PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 417 lines; `PRD_FINALIZED.md`: 419 lines — **+2 lines, +0.48%** (one inserted paragraph plus its blank line; no existing line altered or removed).

## Changes
- **§2.4 Resource Identity, Timestamps and the Logical Clock — insert — every instant a response carries (business instants, caller-supplied instants echoed back, the sweep's `swept_at`, the clock's `current_utc`) is rendered as an ISO 8601 UTC timestamp with exactly three fractional digits and a trailing `Z`; caller-supplied instants are normalized (offset converted to UTC, sub-millisecond precision truncated in the rendering); a null instant field renders as null — `implementation/clock.py:30-35`, `implementation/serializers.py:108-117`, `implementation/routes/ops.py:15,30`.**

This is the only edit; it traces to the sole Step 7 item (17 `test_suite/` call sites relaxed from exact-string to `assert_same_instant` because the impl emits `2026-09-05T00:00:00.000Z` where the fixtures wrote `...T00:00:00Z`, and PRD §2.4 pinned the three-digit spelling only for `created_at`/`updated_at`/`meta.api_request_timestamp`). Step 7 applied no `implementation/` fixes and deleted no tests, so nothing else in the diff reveals a PRD silence or mismatch.

## Per-edit pre-edit search log

**Edit 1 — §2.4 insertion**
- **(a) Subject:** the rendered spelling of every ISO-8601 instant the API emits, including instants supplied by the caller and echoed back.
- **(b) Impl paths enumerated / read or grepped:**
  - `clock.py:30-35` `iso()` — the single renderer: `strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (microsecond // 1000) + "Z"`, returns `None` for `None`, and `astimezone(utc)` first.
  - `clock.py:12-27` `parse_iso()` — all inbound instants are parsed to aware UTC datetimes (`astimezone(timezone.utc)`), so nothing is stored as a raw string.
  - `validation.py:105-114` `field_datetime()` — the only inbound-instant gate; used by `routes/funding.py:29` (`expires_on`), `funding.py:242` (`license_expires_on`), `maintenance.py:25-26` (`window_start`/`window_end`), `properties.py:241` (`hearing_at`), `disposition.py:298` (`performance_deadline`), `ops.py:28` (`to_iso8601`).
  - `serializers.py:108-117` + all 13 field lists — `_value()` converts *any* `datetime` in *any* serialized field to `iso()`, so all of `acquired_at`, `last_mow_at`, `demolished_at`, `listed_at`, `expires_on`, `filed_at`, `adjudicated_at`, `license_expires_on`, `window_start/end`, `completed_at`, `executed_at`, `last_reverter_at`, `hearing_at`, `submitted_at`, `board_decision_at`, `screened_at`, `performance_deadline`, `cure_deadline`, `complied_at`, `reverted_at` share one spelling; `None` stays `None`.
  - Non-record response bodies: `routes/ops.py:15` (`swept_at` → `iso()`), `routes/ops.py:30` (`current_utc` → `iso()`), `response.py:19` (`meta.api_request_timestamp` → `wall_now_iso()`), `services.py:611-645` `inventory_summary()` and `calculations.disposition_price_quote` via `routes/properties.py:152-158` (verified: no instant fields at all).
  - Server-stamped instants all come from the logical clock (`routes/properties.py:147,181,220`; `maintenance.py:165,171,173,275`; `disposition.py:148,169,237,285,342,415`; `funding.py:209`; `services.py:513-514,529,551,569,575,603`) and are stored as datetimes, never pre-formatted strings.
  - Grep for `strftime|isoformat|iso(` confirmed `clock.iso` is the only formatter in the codebase.
- **(c) Wording adjustments made:** (1) used "among them" rather than an exhaustive list, so the claim is not falsified by any instant field the list omits; (2) scoped the truncation claim to "in the rendering" only — the stored datetime keeps microsecond precision and deadline/window comparisons run at that precision, so a blanket "truncated" claim would have mis-described `services.py:538,549,563` and `maintenance.py`'s window arithmetic; (3) added the explicit "renders as null" clause because `iso(None) → None` and many of the listed fields are null for most of their lifetime — without it, "all rendered as ISO 8601 timestamps" would have wrongly forced a string onto `cure_deadline`, `complied_at`, `reverted_at`, etc.; (4) said "an offset is converted to UTC" rather than describing full parser leniency (naive instants, lowercase `z`), keeping the sentence under-determined on acceptance rules that Step 7 never probed.

## Step 9: Complete PRD — 2026-09-02T07:11:51.455Z

`PRD_COMPLETED.md` is written. Verified every route, service, calculation and validator against the PRD prose.

**Source vs completed**: `PRD_FINALIZED.md` 419 lines / 82,966 chars → `PRD_COMPLETED.md` 419 lines / 88,538 chars (**+5,572 chars**, 19 diff hunks, no new sections, no new paragraphs — all inserts are in-paragraph).

**Counts**: 24 ambiguity-pins, 8 mismatch-revisions.

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `implementation/response.py:12`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from wall-clock time, not the logical clock — `implementation/response.py:19`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; absent-or-empty falls back to the default — `implementation/validation.py:137`
- §2.3 — insert — ambiguity — `created_at` ties (logical clock collisions) broken by write order; descending hearing list breaks `hearing_at` ties by later `created_at` then later write — `implementation/db.py:83`, `implementation/routes/properties.py:266`
- §2.3 — insert — ambiguity — a filter value outside the field's enumeration is `ERR_INVALID_REQUEST`; an unknown id just matches nothing — `implementation/validation.py:174`
- §2.4 — insert — mismatch — a record touched several times in one request advances `version` by exactly 1; the applicant roll-up refresh bumps only when a value actually changes (forced on reverter) — `implementation/db.py:61`, `implementation/services.py:263`
- §2.8 — revise — mismatch — "may take no further commitment" narrowed to *acquisition* commitment; scheduling work / planning runs on an expired source is not blocked — `implementation/routes/maintenance.py:87`, `:213`
- §3.1 — insert — ambiguity — both code-enforcement counts required and zero-or-more — `implementation/routes/properties.py:98`
- §3.1 — insert — ambiguity — `tax_year` required integer 1900–2200, balance zero-or-more — `implementation/routes/properties.py:112`
- §3.2 — insert — ambiguity — `recapture_cents` zero-or-more (nil receipt accepted, still bumps `version`), `tax_year` 1900–2200, an already-`EXPIRED` source keeps its terminal status — `implementation/routes/funding.py:74`
- §3.2 — revise — mismatch — "`EXPIRED` funds nothing at all" replaced: completion → `ERR_FUNDING_SOURCE_EXPIRED`; board approval on an expired source reports `ERR_FUNDING_CONSTRAINED`; expiry tested nowhere else — `implementation/routes/funding.py:173`, `implementation/routes/maintenance.py:159`
- §3.3 — insert — ambiguity — restriction tested at packet open (`ERR_FUNDING_RESTRICTION_VIOLATION`); source status and parcel custody not examined then — `implementation/routes/funding.py:114`
- §3.3 — insert — ambiguity — close on a non-`PROSPECT` parcel is `ERR_PROPERTY_NOT_IN_INVENTORY`, tested before segregation of duties — `implementation/routes/funding.py:194`
- §3.4 — insert — ambiguity — the open-action test is the only guard on filing: any custody, and a `CLEAR` title is driven to `QUIET_TITLE_FILED` too — `implementation/routes/properties.py:171`
- §3.5 — insert — ambiguity — expiry tested straight after order status; no custody or window re-test at completion — `implementation/routes/maintenance.py:156`
- §3.6 — insert — mismatch — the pre-ranking live-variant refresh leaves candidates' `version`/`updated_at` untouched — `implementation/services.py:452`
- §3.6 — revise — ambiguity — residual ranking tie broken by write order — `implementation/services.py:461`
- §3.6 — insert — ambiguity — execution re-check is exactly the three named tests (score, structure, ward not re-tested); re-score bumps no version, only survivors' — `implementation/routes/maintenance.py:249`
- §3.6 — insert — ambiguity — run-created orders bypass every §3.5 gate and may drive `available_cents` negative — `implementation/routes/maintenance.py:266`
- §3.7 — insert — ambiguity — any custody other than `ACQUIRED`/`REVERTED` (incl. `LISTED`) gives `ERR_PROPERTY_NOT_IN_INVENTORY`, both custody tests ahead of the title test — `implementation/routes/properties.py:139`
- §3.7 — insert — ambiguity — price quote takes a required `program` query param, validated before the parcel is resolved, and reads any custody/title state — `implementation/routes/properties.py:151`
- §3.7 — insert — mismatch — drafting tests neither custody nor title (PRD said "against a listed parcel") — `implementation/routes/disposition.py:73`
- §3.7 — insert — ambiguity — submit only from `DRAFT`, else `ERR_APPLICATION_INVALID_STATE` — `implementation/routes/disposition.py:140`
- §3.7 — insert — ambiguity — governing hearing residual tie broken by later write — `implementation/services.py:302`
- §3.7 — revise — mismatch — `ERR_OFFER_BELOW_QUOTE` now precedes `ERR_HOMEOWNER_LIMIT_EXCEEDED` (and the revision-limit test sits between), per the §2.12 ladder — `implementation/services.py:354`
- §3.8 — insert — ambiguity — `information_requested` required 1–1,000 chars, retained but not in the response shape; request-info/resubmit from other statuses are `ERR_APPLICATION_INVALID_STATE`; omitted resubmit fields keep stored values — `implementation/routes/disposition.py:205`, `:220`
- §3.8 — revise — mismatch — recommend guards reordered to the actual evaluation order: title, custody, screening outcome, segregation — `implementation/routes/disposition.py:250`
- §3.8 — revise — mismatch — board-decision `resolution_no` is required but not echoed; `denial_reason` is optional (≤500 chars) and stays null — `implementation/routes/disposition.py:273`
- §3.9 — revise — ambiguity — a negative `abatement_years` also draws `ERR_ABATEMENT_YEARS_EXCEED_CAP`, not a shape error — `implementation/routes/disposition.py:317`
- §3.9 — insert — ambiguity — `completed_count` may be zero; `evidence_reference` 1–500 chars — `implementation/routes/disposition.py:390`
- §3.9 — revise — ambiguity — sweep steps two and three use strictly-before comparisons, and step three reverts agreements step two just moved into cure (counted in both tallies) — `implementation/services.py:544`
- §3.9 — insert — ambiguity — a ward narrows `cure_pending_count` via the agreement's parcel but never the four ledger totals — `implementation/services.py:611`

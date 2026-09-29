# Worklog — task_2593_data_center_white_space_fit_out

## Step 1: Create task directory — 2026-09-03T16:05:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2593_data_center_white_space_fit_out` and its `workspace/` subdirectory. Index 2593 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-03T18:14:00.000Z

All three artifacts are complete and the linter is clean.

## Output files (`/home/ubuntu/github/CodingPRD/tasks/task_2593_data_center_white_space_fit_out/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3443 | scenario, domain_name, api_prefix, role_groups, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no `scaffold_*_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2036 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6882 | `scaffold_corner_design` only |

All three parse under `yaml.safe_load`.

## SCAFFOLD.yaml scale
15 entities, 73 endpoints, 13 state machines, 2 `concurrency_rules`, 13 calculations, 49 validation priorities, 61 error codes, 9 roles. `complexity_profile`: layers `[dual_variant_calculation, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency, multi_tenancy_isolation]`, `entity_topology: graph`, `state_machine_shape: branching`, `consistency_model: immediate`.

## §1.8 rule ids (19 instances)
`dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

## §1.9 sections (118 instances: 89 full recipes + 29 `excluded_because` stubs)
`entities` 19 · `state_machines` 29 · `calculations` 18 · `validations` 9 · `endpoints` 7 · `errors` 19 · `rbac` 9 · `cross-cutting complexity layers` 7 · `consistency model` 1

Every stub's `difficulty_instance` resolves to a real §1.8 instance name; all 137 names are unique across the union of both files; all 61 error codes are reachable from §1.9 (the last three — `ERR_TENANT_SCOPE_VIOLATION`, `ERR_STALE_CAGE_VERSION`, `ERR_STALE_HALL_VERSION`) landed in the cross-cutting section.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2593_data_center_white_space_fit_out/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2593_data_center_white_space_fit_out/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2593_data_center_white_space_fit_out/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     89
  Calls scanned (§1.8+§1.9):  1534

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Three scaffold fixes the linter forced (all in `SCAFFOLD.yaml`)
- `POST /racks` input: `u_height` → `"u_height?"` (the field carries `default: 42`, so the defaults corner test legitimately omits it).
- `GET /mops/{mop_id}/approvals` → `GET /mops/{id}/approvals`; check (f) matches the sub-resource form literally as `/<parent>/{id}/<segment>`, so `{mop_id}` left `MopApproval.mop_id` reverse-unreachable.
- Consistency pass in both design files: 49 numeric `grid_row: 1` payload values quoted to `"1"` to match `Rack.grid_row type: string`.

## Step 3: Copy shared files — 2026-09-03T18:16:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T18:33:00.000Z

PRD complete and verified.

## Output
`workspace/PRD.md` — **570 lines**, written incrementally (1 `Write` + 6 heredoc appends + 2 small `Edit` corrections), ending cleanly on the last row of the §5 error table with no audit footer and no truncation.

## Section list
- §1 Introduction
- §2 Global Specifications & System-Wide Principles (2.1 Personas/Headers/RBAC; 2.2 API Response Structure — byte-verbatim fixed block; 2.3 Pagination; 2.4 Common Resource Properties, Identity and the Logical Clock; 2.5 Path Resolution Order and Cross-Parent Consistency; 2.6 Human-Readable Identifiers and Layout Uniqueness; 2.7 kW Arithmetic: Precision, Rounding and Electrical Constants; 2.8 Proving a Current View: Optimistic Concurrency; 2.9 Derived Fields, Cascade Discipline and Conserved Quantities; 2.10 The Order of Rejection)
- §3 Business Logic & Workflows (3.1 Halls/Tenants/Phase Ladder; 3.2 PDUs and Busway Runs; 3.3 Branch Feeds and the White Space Power Ledger; 3.4 Layout/Installation/Energisation of Rack Positions; 3.5 Containment, Airflow and the Thermal Gate; 3.6 Cages, Cameras and Card Readers; 3.7 Phased Commissioning: Packages, Load Banks, Independent Witnessing; 3.8 Change Control in Live Space: MOPs; 3.9 Capacity Release to Operations)
- §4 API Endpoint Definitions
- §5 Error Code Reference

## Coverage
| Item | Scaffold | Documented |
| --- | --- | --- |
| Entities | 15 | 15 (all named in prose; `MopApproval`'s `common_fields: false` exception called out in §2.4 and §3.8) |
| Endpoints | 73 | 73 rows, 4 columns, generated directly from the scaffold |
| State machines | 13 | 13, every declared state value present as its own backticked span (incl. the two-dimensional `CommissioningPackage` and re-entrant `SUSPENDED`) |
| Calculations | 13 | 13, with pinned rounding order, both dual variants (`DESIGN`/`COMMISSIONED`, nameplate/airflow under `min()`), and all constants (1.732, 0.95, 0.80, 1.045, 0.85, 1.08, 3412, negative-25.00 margin, 0.95/8.0 load-bank, 60-minute buffer, limits 2) |
| Validation priorities | 49 | 49, enumerated 1–49 in §2.10; ladder order, error IDs and HTTP statuses machine-diffed against the scaffold — zero mismatches |
| Error codes | 61 | 61 rows in §5, all unique; every one also appears in §1–§3 prose |
| Roles | 9 | 9, all backticked, with opaque vs `entity_backed:Tenant` identity semantics |

## Hard Contract results (report only — not written into any file)
- **Contract 1 — Field-Name Coverage: PASS.** 144 required identifiers (125 distinct entity field names + all endpoint `input`/path-param identifiers). Two passes run, the second under the strict rule that each token must appear as its *own* backticked span. Misses: 0.
- **Contract 2 — Rule Coverage: PASS.** All 49 validation priorities in scaffold order with matching error IDs and statuses; both `concurrency_rules` (`expected_cage_version`/`ERR_STALE_CAGE_VERSION`, `expected_hall_version`/`ERR_STALE_HALL_VERSION`, both 412) in §2.8; every transition with preconditions and side effects; all 13 calculations with formulas, constants, input sets and precision; `applies_to` scopes stated (e.g. the thermal gate's exact three operations, and the `decision == WITNESSED` narrowing); sibling-branch symmetry documented for MOP close vs back-out, witness `WITNESSED` vs `REJECTED`, and the two capacity variants.
- **Contract 3 — §3 Path Purity: PASS.** 995 backticked spans in §3 (307 distinct); zero begin with `/`, zero are a bare HTTP method, zero combine method+path, and zero contain `/` at all. §1–§2 were also scanned and are path-free.

## Two corrections caught by the verification pass
1. `ABORTED` and the `RUNNING → COMPLETED` transition were described but not named as backticked state values in §3.7 — fixed.
2. §3.5 originally said the thermal gate applies to "recording a witness decision"; the scaffold narrows it to `decision == WITNESSED` only. Fixed, with the `REJECTED` exemption stated explicitly so it matches §3.7.

## Scaffold quirks resolved deterministically (noted for the implementer's benefit)
- **`page`/`page_size` vs `limit`/`offset`:** all 73 endpoints declare `page?`/`page_size?`, but `pagination_defaults` specifies `limit`/`offset`. Documented `limit`/`offset` as canonical with their exact defaults, `page_size` as a synonym for `limit`, `page` as a one-based index, and `limit`/`offset` winning when both spellings appear.
- **`RackFeed.feed_side`** is both an input and a `computed` field ("copied from the busway"). Documented as declared in the request but recorded from the named busway.
- **`CoolingUnit.redundancy_role`** is an input enum the cooling model never reads; documented explicitly that the hall's `cooling_redundancy` stance, not the per-unit role, withholds the largest duty contribution.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per command instruction):** `wc -l` = 570; `tail -20` ends on the final `| ERR_BREAKER_DERATE_EXCEEDED | 422 |` row of the §5 table — a real section boundary, not mid-sentence. Section headings enumerate cleanly §1→§5. 61 `ERR_` rows and a complete §4 endpoint table present. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T19:12:00.000Z

The implementation for task 2593 is complete.

## Modules (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `services/calc.py` | 611 |
| `routes/commissioning.py` | 314 |
| `routes/mops.py` | 302 |
| `routes/electrical.py` | 269 |
| `routes/halls.py` | 229 |
| `routes/mechanical.py` | 225 |
| `routes/racks.py` | 202 |
| `routes/release_packets.py` | 186 |
| `validation.py` | 187 |
| `db.py` | 171 |
| `routes/security.py` | 168 |
| `errors.py` | 145 |
| `response.py` | 143 |
| `services/cascade.py` | 141 |
| `constants.py` | 136 |
| `app.py` | 77 |
| `util.py` | 52 |
| `output.py` | 42 |
| `middleware.py` | 41 |
| **total** | **3641** (plus `start.sh`, `requirements.txt`, two empty `__init__.py`) |

## Endpoint count

**73 / 73.** Diffed the live Flask `url_map` against the 73 `method`+`path` pairs in `SCAFFOLD.yaml`: exact match, with the sole cosmetic difference that the approval-trail sub-resource is declared `<mop_id>` rather than `{id}` (same URL shape, same `ERR_MOP_NOT_FOUND`).

`python3 -m compileall` clean on every `.py`. Storage is module-level dicts in `db.py` only — a grep for `sqlite`/`open(`/`json.dump`/`/tmp`/`pickle` across all sources returns nothing, and nothing is seeded at import.

## Smoke test (port 18593, own PID killed afterwards; `ss` confirms port free)

- Hall create → 201, envelope exactly `meta{api_request_id, api_request_timestamp}` / `response_type` / `data`; ledger opens at `committed_kw 0.00`, `commissioning_reserve_kw 25.00`, `spare_kw 975.00` (identity holds), `version 1`.
- Read back, list (`response_type: array` with `limit/offset/total_count/has_more`), `page`/`page_size` aliases honoured.
- Error envelope verified across the ladder: `ERR_UNAUTHENTICATED` 401, `ERR_UNAUTHORIZED` 403, `ERR_MISSING_USER_ID` 401, `ERR_VALIDATION` 422, `ERR_HALL_NOT_FOUND` 404, `ERR_DUPLICATE_CODE` 409, `ERR_HALL_PHASE_INVALID` 409, `ERR_PHASE_PREREQ_NOT_MET` 409, `ERR_STALE_CAGE_VERSION` 412, `ERR_RELEASE_SCOPE_EMPTY` 422, `ERR_TENANT_SCOPE_VIOLATION` 403, `ERR_MOP_TARGET_NOT_FOUND` 404, `ERR_APPROVER_IS_AUTHOR` 422, `ERR_OUTSIDE_EXECUTION_WINDOW` 409.
- Arithmetic spot-checks: busway `raw_kw` 273.136 and DESIGN `usable_kw` 218.51 for 400 A / 415 V / N; rack `chargeable_kw` 10.45 from `design_kw` 10.00; ledger 1000 − 6 − 25 = 969 after one feed.
- Full MOP lifecycle exercised end to end (draft → submit → approve → schedule → execute → close, and a second one through back-out): `release_posture` stays `OPEN` at `SCHEDULED` with `open_mop_count 1`, flips to `LOCKED` at `IN_EXECUTION`, and returns to `OPEN` with the busway restored to its captured `pre_execution_target_state` after close/back-out. Approval quorum is 1 for LOW/MEDIUM and the immutable trail rows carry only `id`/`created_at` (no `version`/`updated_at`), as `common_fields: false` requires.
- Tenant isolation confirmed both ways: 403 on foreign cage detail, silent filtering on the release-packet list.

Two fixes were needed along the way: `constants.py` was missing the long-form role aliases and `MOP_AUTHOR_ROLES`/`TOPOLOGIES` that the route modules import (added), and `db.assign()` was introduced so derived-field recomputes that change nothing no longer bump `version`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so `test_suite/` did not exist when the implementation generator started — physical isolation held.

## Step 5: Generate Unit Tests — 2026-09-03T20:03:00.000Z

Stage 2 is complete. Both output directories are at the **task root**, not under `workspace/`.

## Files

`test_helpers/` (unchanged from Stage 1 except one constant fix, 2631 lines): `__init__.py` 85, `api_client.py` 299, `api_errors.py` 136, `assertions.py` 234, `constants.py` 75, `factories.py` 191, `fixtures.py` 1013, `test_users.py` 99, `types.py` 499.

`test_suite/` (10786 lines, 204 tests):

| file | lines | tests | queue |
|---|---|---|---|
| conftest.py | 72 | — | — |
| test_01_electrical_chain_ceilings.py | 447 | 8 | A |
| test_02_power_ledger_and_reserve_tiers.py | 388 | 8 | A |
| test_03_containment_cooling_and_thermal_gate.py | 278 | 6 | A |
| test_04_cage_security_coverage.py | 122 | 3 | A |
| test_05_commissioning_packages_and_load_banks.py | 217 | 4 | A |
| test_06_change_control_windows_and_revisions.py | 332 | 6 | A |
| test_07_mop_execution_cascade_and_compensation.py | 202 | 4 | A |
| test_08_entity_contracts.py | 1074 | 19 | B entities |
| test_09_state_machine_transitions.py | 820 | 16 | B state_machines |
| test_10_lifecycle_state_machines.py | 802 | 12 | B state_machines |
| test_11_calculation_boundaries.py | 812 | 16 | B calculations |
| test_12_validation_ordering.py | 929 | 18 | B validations |
| test_13_endpoint_contracts.py | 560 | 10 | B endpoints |
| test_14_error_catalogue.py | 1558 | 33 | B errors |
| test_15_role_based_access.py | 1263 | 23 | B rbac |
| test_16_cross_cutting_and_consistency.py | 910 | 18 | B cross-cutting + consistency |

## Coverage audit (scripted against both yamls)

- **Queue A: 39 tests / 19 of 19 instances, ≥2 each — zero shortfalls.**
- **Queue B: 165 tests / 89 of 89 non-stub instances, ≥1 each — zero shortfalls.** None of the 29 `excluded_because:` stubs was translated.
- Every test carries exactly one `Design:` line, it is the last docstring line, and all 204 resolve to a real yaml `name:`. No untagged, dual-tagged or unresolved tags.
- All PRD citations verified line-by-line: every wrapped quote line is a verbatim substring of a single `PRD.md` line (`grep -F` equivalent) — 0 failures.
- No `pytest.mark.skip/skipif/xfail` anywhere; `py_compile` passes on all 26 files; pyflakes reports no undefined or unused names in `test_suite/`; a static resolution pass confirms every `test_helpers` import, `api_client.<method>` and `ApiErrorId.<member>` exists; no duplicate test names.

## Skipped instances (2 partial, 0 whole)

- `Corner/errors/live_space_change_control_errors_mop_required_risk_class_and_locked_posture` — the covering-MOP **success branch** was dropped: the recipe uses `target_resource_type: "PDU"`, but PRD §3.8 enumerates only `BUSWAY`, `COOLING_UNIT`, `CONTAINMENT_ZONE`, `RACK`, so the outcome is not uniquely derivable. The instance's three error branches are covered.
- `Corner/cross-cutting complexity layers/tenant_scoped_uniqueness_and_cage_tenant_coherence` — the `tenantless_rack_inside_the_cage_rejected` probe was dropped: the PRD only forbids a tenant that "contradicts" the cage's tenant, and a null `tenant_id` does not verbatim contradict it. The instance's other four probes are covered.

No whole instance was skipped; every other recipe was verbatim-covered by the PRD.

## Adjudications where the PRD overruled a yaml literal (worth knowing when the implementation lands)

1. `busway_usable_kw_nested_min_with_topology_branch` wants `Busway.status == PLANNED`; PRD §3.2 says a new run sits at `INSTALLED` — tests assert `INSTALLED`.
2. `mop_approvals_after_reject_rejected` wants `approval_count == 1` after a REJECT; PRD says REJECT/REQUEST_REVISION never count — tests assert `0` (consistent with queue A).
3. `ERR_RELEASE_SCOPE_EMPTY` is 422 per §2.10 level 39, not the recipe's 409.
4. `package_state` after script approval is `IN_EXECUTION` (§3.7), not the recipe's `SCRIPT_APPROVED`.
5. Released feeds are hidden from feed listings unless `include_released` is set; `custody_fitout_count` counts PLANNED + INSTALLED + AT_RISK.
6. A feed may be reserved against an `INSTALLED` run, so the busway-state-before-derate ordering test drives the run to `ISOLATED` instead.
7. One fix landed in `test_helpers/constants.py`: `TENANT_CONTRACT_START` was the bare date `"2026-08-01"`, but PRD §2.2 requires an "ISO 8601 UTC start instant" — changed to `"2026-01-01T00:00:00Z"` (two independent generators flagged it; no test asserts the old value).

One assertion was dropped rather than weakened: `chargeable_kw` for a 1.00 kW rack (1.00 × 1.045 makes half-up rounding ambiguous). Nothing else was softened.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both confirmed present at the task root; `workspace/` contains no stray copy of either.

## Step 7: Run Tests and Iterate — 2026-09-03T20:34:00.000Z

All 8 rounds of a single sweep report `passed == total` (204/204 each, 0 failed, 0 errors, 0 skipped).

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 196/204 in all 8 rounds, with an identical, perfectly deterministic 8-test failure union (no load-induced flakiness). Sweep 2 after fixes: 204/204 in all 8 rounds.

**Tests deleted:** none. Every failure traced to a verbatim PRD sentence and was either an implementation defect or a test-side bug; no PRD-silence or non-unique-derivability collapse applied.

**Fixes applied to `implementation/`:**

- `implementation/util.py` — added `Instant` (a `datetime` subclass that remembers the exact ISO text it was parsed from) and made `parse_iso` return it, retaining the raw text only when it is already a `...Z` UTC rendering. Why: PRD §2.4 reserves the three-fractional-digit rendering for `created_at`/`updated_at` and says the clock "echoes that instant back", so a client- or clock-supplied instant must round-trip verbatim.
- `implementation/response.py` — `format_dt` now prefers the remembered raw text before falling back to the three-digit `strftime`. Why: same rule; this fixes `window_start`/`window_end`, `executed_at`, `closed_at` and `released_at` at once while leaving server-minted `created_at`/`updated_at`/`api_request_timestamp` at three digits. Previously `window_start` came back as `2026-08-06T02:00:00.000Z` instead of the supplied `2026-08-06T02:00:00Z`, and `executed_at`/`closed_at` as `2026-08-05T02:30:00.000Z` instead of the clock's `2026-08-05T02:30:00Z`.
- `implementation/routes/racks.py`, `create_rack` — added the level-8 check that a supplied `tenant_id` may not contradict the cage's `tenant_id`, raising `ERR_HALL_MISMATCH` (422). Why: PRD §2.5 verbatim — "a cage's tenant may not contradict the tenant of the racks the cage already contains… Any of those disagreements is rejected with `ERR_HALL_MISMATCH` (HTTP 422) on rack creation…". It sits with the other §2.5 mismatch checks, ahead of grid-position uniqueness (level 11), so a refused placement still leaves its grid slot free.

**Fixes applied to test-side files** (both in `test_suite/`; `test_helpers/` needed no change):

- `test_suite/test_13_endpoint_contracts.py`, `TestBuswayEnergiseAction._planning_hall_with_an_installed_run` — the fixture called `commission_pdu(...)` but discarded its result, so the test then asserted `COMMISSIONED` against the stale `PLANNED` create response. Now rebinds `pdu_a = commission_pdu(...)`. Pure stale-object bug; assertion strength unchanged.
- `test_suite/test_14_error_catalogue.py`, `TestAuthLadder` (two tests) — both verified "no hall was left behind" via `GET /halls?code=…`, but PRD §4 lists `GET /halls` as "Lists white spaces with pagination" with no `code` filter, so the unknown param is ignored and `total_count` was 1, not 0. Rewritten to list all halls (`limit=100`) and assert the rejected codes are absent and `total_count == 1`. Equivalent-or-stronger check that no longer depends on an unspecified filter; no `code` filter was added to the implementation, since that capability traces to no PRD sentence.

Note on method: `workspace/sweep.log` cannot be used for per-test verdicts — eight concurrent pytest `-v` processes append to one file and the PASSED/FAILED tokens attach to the wrong node-id lines. Verdicts were read from `results.1..8.json`; only the single-line `FAIL <name>: <message>` records in the log are reliable, and those supplied the failure messages.

**Orchestrator independent verification:** re-read all 8 `workspace/implementation/results.*.json` directly (all present, ~65 KB each, mtime 20:32). Every round: `passed 204 / failed 0 / total 204 / errors 0 / skipped 0`. Sweep artifacts confirmed, not merely claimed. Step 8 therefore runs (Step 7 applied 3 implementation fixes + 3 test-side fixes ≠ zero-iteration exit).

## Step 8: Finalize PRD — 2026-09-03T20:41:00.000Z

Done. `PRD_FINALIZED.md` written with four edits (five bullets; two land in §2.4).

## Line counts
- `PRD.md`: 570 lines → `PRD_FINALIZED.md`: 574 lines (+4, **+0.70%**)

## Changes

- **§2.3 (Pagination)** — *insert* — pinned that a query parameter the addressed endpoint does not define is ignored rather than rejected (no error, no narrowing), and that offered field filters select by exact string equality. — `implementation/output.py:24-31`, `implementation/response.py:110-138`
- **§2.4 (Common Resource Properties / Logical Clock)** — *insert* — new "How instants are rendered back" paragraph: three-fractional-digit rendering belongs to `created_at`/`updated_at`/`api_request_timestamp`; every other instant a resource carries (`contract_start_date`, `window_start`, `window_end`, `released_at`, `executed_at`, `closed_at`) is echoed back with exactly the text it entered as when that text already ends in `Z`, otherwise re-rendered canonically with three digits. — `implementation/util.py:37-84`, `implementation/response.py:29-38`, `implementation/db.py:49,63-72,116,166`
- **§2.4 (Logical clock)** — *revise* — the clock capability returns a `current_utc` field holding the supplied text verbatim *whatever form it took* (the one place a non-`Z` form is not canonicalised). — `implementation/routes/halls.py:30-38`
- **§2.5 (Cross-parent consistency)** — *revise* — spelled out the rack-creation direction of the cage/tenant agreement rule: a rack placed inside a cage while naming its own `tenant_id` must name that cage's tenant; a rack with no `tenant_id`, or no `cage_id`, contradicts nothing. — `implementation/routes/racks.py:63-66`
- **§3.1 (Reconciliation view)** — *revise* — replaced the ambiguous "Hall and tenant lists may be narrowed by `status`, `tenant_mode` and `code` respectively" with explicit per-list filters and an explicit statement that the hall list has no `code` filter. — `implementation/routes/halls.py:102,223`

No PRD change for the `test_13` fixture bug (stale `commission_pdu` result — PRD §2.2 already pins that a modifying operation returns the updated resource).

## Per-edit pre-edit search log

**Edit 1 — unknown query parameters.** (a) Subject: query-parameter handling on every endpoint. (b) Enumerated: `output.py::filtered` (exact-match spec, unknown params never consulted); every `filtered(...)` callsite — `routes/halls.py:102,223`, `racks.py:99`, `electrical.py:51,139,235`, `mechanical.py:70,173`, `security.py:76,144`, `commissioning.py:80,244`, `mops.py:78`, `release_packets.py:89` (all specs are string fields only, no numeric/enum coercion or validation); `response.py::read_pagination` (`limit`/`offset`/`page`/`page_size` *are* validated → `ERR_VALIDATION`); `electrical.py:239` `include_released` via `validation.truthy`. (c) Adjustment: scoped the claim to parameters "the addressed endpoint does not define" so the validated pagination params are untouched, and narrowed the equality sentence to "field filters" so the non-equality `include_released` toggle is not mis-described.

**Edit 2 — instant rendering.** (a) Subject: serialisation of every datetime-valued field. (b) Enumerated by grep for `_at"`/`_date"`/`datetime_field`/`clock_now`: `util.py::Instant/parse_iso` (raw kept only when the text ends in `Z`), `response.py::format_dt`/`jsonify_value`/`iso_now` (created_at/updated_at/api_request_timestamp are pre-formatted wall-clock strings, never re-echoed), `db.py:49` (`CLOCK_DEFAULT = "2026-08-01T00:00:00Z"`), `db.py:116,166` (row stamps), `halls.py:203,213` (`contract_start_date`), `mops.py:39-41,58,181-200` (`window_start`/`window_end` at draft and revise), `mops.py:264,286` (`executed_at`, `closed_at`), `commissioning.py:204-227` (load-bank window), `electrical.py:223,261` (`released_at`); `db.py::clock_iso` confirmed unused; approval rows carry only `created_at`. (c) Adjustment: first draft said "every other instant *the API returns*", which would have falsely covered the clock endpoint's echo (it returns `payload["current_utc"]` verbatim even for `+00:00` form) — re-scoped to "every other instant *a resource carries*" and pinned the clock echo separately in edit 3. Verified live against a running server: `+00:00` input → `2026-01-01T00:00:00.000Z`, `Z` input → echoed verbatim, clock echo verbatim in both forms.

**Edit 3 — clock echo.** (a) Subject: `POST /_clock/set_current_utc` response body. (b) Enumerated: `routes/halls.py:30-38` (returns `{"current_utc": payload["current_utc"]}`, bypassing `format_dt`), `db.py::set_clock/clock_now`, and every clock reader (`mops.py:105,250-251,264,286`, `commissioning.py:265-266`, `electrical.py:261`) to confirm the stored value is the parsed `Instant` while only the response is the raw text. (c) Added "whatever form that text took" to distinguish this endpoint from the resource-field rule of edit 2.

**Edit 4 — cage/tenant agreement.** (a) Subject: rack↔cage tenant consistency and `ERR_HALL_MISMATCH`. (b) Enumerated every `ERR_HALL_MISMATCH` raise: `racks.py:59-66` (zone hall, cage hall, cage-vs-tenant), `electrical.py:105-106` (busway declared hall vs PDU hall), `electrical.py:186-187` (feed busway hall vs rack hall), `release_packets.py:48-49` (cage hall vs packet hall); plus `security.py::create_cage` (no tenant/rack check at all — vacuous, a new cage can contain no racks), `racks.py::tag_rack`/`install_rack` (no path mutates `rack.tenant_id`). (c) Wording restricted to rack creation and made explicitly conditional on both `cage_id` and `tenant_id` being named, so the null-tenant and null-cage paths are not mis-described and no new obligation is implied for cage creation (whose entry in the existing PRD list stays untouched and vacuous).

**Edit 5 — hall/tenant list filters.** (a) Subject: filters offered by `GET /halls` and `GET /tenants`. (b) Enumerated: `routes/halls.py:102` (`status`, `tenant_mode` only), `routes/halls.py:223` (`code` only), §4 rows for both endpoints, and `output.py::filtered` for the ignore-unknown behaviour that makes `?code=` a no-op on halls. (c) None — wording matches both callsites and is consistent with edit 1.

## Step 9: Complete PRD — 2026-09-03T21:15:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md`, rather than one subagent scanning all 21 implementation modules. The implementation is 3641 lines across 21 modules; a single-pass scan of that surface reliably degrades into a no-op that leaves `PRD_COMPLETED.md` byte-identical to its source. Partition: pass A = infra + halls/tenants + electrical; pass B = racks/mechanical/security + services/calc.py + services/cascade.py; pass C = commissioning/mops/release_packets. Pass A created the file from `PRD_FINALIZED.md`; B and C edited it in place, each carrying forward the prior pass's hand-off notes so ownership never overlapped.

### Pass A — infra, halls, electrical

- **PRD_FINALIZED.md**: 574 lines, 116,945 chars → **PRD_COMPLETED.md**: 574 lines, 123,615 chars (**+6,670 chars**, 0 new lines; all edits in-paragraph)
- **18 changed lines: 16 ambiguity-pins, 2 mismatch-revisions**

- §2.1 Identity semantics — insert — ambiguity — an `X-User-ID` present but empty counts as missing for `ERR_MISSING_USER_ID` — `middleware.py:22-26`
- §2.1 Tenant isolation — insert — ambiguity — a `TenantRepresentative` omitting `X-User-ID` is not rejected for the header; it matches no tenant, so the four scoped detail/summary reads give `ERR_TENANT_SCOPE_VIOLATION` and the three list surfaces return empty — `middleware.py:41`, `routes/halls.py:167`
- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` — `response.py:12,21`
- §2.3 Pagination — insert — ambiguity — `limit`/`offset`/`page_size`/`page` must be integers (whitespace, `+`, leading zeros tolerated) and out-of-range values are rejected with `ERR_VALIDATION` 422, not clamped — `response.py:93-138`
- §2.3 Pagination — insert — ambiguity — equal `created_at` ties break on server creation order; pagination params are read only after path resolution, so a bad path variable outranks a bad pagination param — `response.py:141-147`
- §2.4 Common properties — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from the host's real wall clock, wholly independent of the logical clock — `response.py:24-26`, `db.py:166`
- §2.4 How instants are rendered back — insert — ambiguity — verbatim echo requires an **upper-case** `Z`; lower-case `z`, numeric offsets and zone-less texts are re-rendered; well-formedness is whatever the parser accepts, incl. date-only text read as midnight UTC — `util.py:65-84`
- §2.4 Recomputation counts as mutation — revise — **mismatch** — at most one `version` bump per row per request; a recompute landing on identical values bumps nothing (a declared transition always does); a row is never bumped by its own creating request (returns at `version` 1, `updated_at` == `created_at`); all rows bumped in one request share one `updated_at` — `db.py:99-131`
- §2.6 Identifiers — insert — ambiguity — `name` carries no length bound and accepts the empty string (hall, tenant, PDU, busway) — `validation.py:35-50`, `routes/halls.py:45`
- §2.7 kW arithmetic — insert — ambiguity — decimal-place rules describe the rounded value, not a format; figures serialise as JSON numbers so `25.00` goes on the wire as `25.0` — `response.py:45-54`
- §2.10 item 4 — revise — **mismatch** — "2 decimal places on kilowatt fields" → each field's own declared limit (no limit ⇒ any precision); plus: fields checked in spec order, first failure wins; JSON `null` ≡ omitted; no type coercion (`"10"`, `10.0` for an int field, `true` all rejected); absent/unparseable body reads as `{}`, non-object body is `ERR_VALIDATION` — `validation.py:11-103`
- §2.10 item 6 — insert — ambiguity — body FKs resolve in spec order; earliest unresolvable reference decides the 404 — `routes/electrical.py:102-104`, `routes/electrical.py:183-184`
- §3.2 PDU creation — insert — ambiguity — adding a unit is legal in any hall phase incl. `LIVE` and is not change-controlled — `routes/electrical.py:22-44`
- §3.2 Busway creation — insert — ambiguity — optional `hall_id` echo is tolerated and must name the parent unit's hall (null/omitted fine); `feed_count` is the count of feeds at `RESERVED`/`ENERGIZED`/`DERATED`; creation needs no MOP in any phase — `routes/electrical.py:100-106`, `services/calc.py:98-106`
- §3.2 Energising — insert — ambiguity — energising needs no covering MOP even in a `LIVE` hall — `routes/electrical.py:152-168`
- §3.3 Feed reservation — insert — ambiguity — `requested_kw` declares no decimal-place limit; payload `feed_side` must be present and in-domain but its value is discarded and may contradict the busway's side without error — `routes/electrical.py:179-180`, `routes/electrical.py:189`
- §3.3 Feed lists — insert — ambiguity — `include_released` is true only for trimmed case-insensitive `1`/`true`/`yes`; the hide is applied after the field filters, so `status=RELEASED` alone returns an empty page — `validation.py:186-187`, `routes/electrical.py:239-240`
- §4 intro — insert — ambiguity — trailing slash insignificant; routing precedes the header ladder, so unknown paths give `ERR_NOT_FOUND` 404 and disallowed methods give `ERR_NOT_FOUND` 405 regardless of headers, and neither identifier is in the §5 catalogue — `app.py:27,47-56`

Pass A hand-off notes: §2.10 items 4 and 6 carry **global** claims verified against all route files. `step_pct_sequence`'s extra rules (max six steps, last element exactly 100) left for pass C. `measured_kw`, `measured_leakage_pct`, `measured_static_pressure_pa` declare no decimal-place limit — item 4 now accommodates that; per-field prose left to B/C. `errors.py` statuses match §5 exactly; `constants.py` matches §2.7/§3.x — no change needed.

### Pass B — racks, mechanical, security, services/calc.py, services/cascade.py

- 574 lines / 123,615 chars → 574 lines / 127,390 chars (**+3,775 chars**, 0 lines)
- **21 edits: 15 ambiguity-pins, 6 mismatch-revisions**

Mismatch-revisions:
- §2.5 — revise — mismatch — dropped "and cage creation" from the `ERR_HALL_MISMATCH` endpoint list; a cage is born empty with independent `hall_id`/`tenant_id` parents, so the code cannot arise there — `routes/security.py:30-45` (no such check) vs `routes/racks.py:59-66`
- §3.4 (as-built tagging) — revise — mismatch — "re-derives the asset-tag completion figure" → "re-derives the computed figures, the asset-tag completion percentage among them"; tagging recomputes all three packet figures — `routes/racks.py:131` → `services/calc.py:504`
- §3.5 (remediation) — revise — mismatch — "optionally records a `remediation_note`" → "optionally carries" one, "accepted as a string or as an explicit null, validated but not persisted, since a zone publishes no such field" — `routes/mechanical.py:120`
- §3.5 (third cascade link) — revise — mismatch — a thermally-blocked L4/L5 package "is re-projected, which brings it to `BLOCKED` unless the package has already been superseded — the branch order of §3.7 keeps `SUPERSEDED` ahead of `BLOCKED`" — `services/calc.py:368-379` with `:354`
- §3.8 (CONTAINMENT_ZONE / RACK bullet) — revise — mismatch — neither target is moved by the execution nor restored by the compensation; a zone-targeted MOP authorises the §3.5 work, a rack-targeted MOP "authorises no write of its own… but it locks the hall's release posture exactly as any other execution does" — `services/cascade.py:61-91`, `:92-125`
- §3.8 (compensation) — revise — mismatch — target restored to `pre_execution_target_state` "in the two cases where a restoration is defined" — `services/cascade.py:92-115`

Ambiguity-pins:
- §3.4 — insert — `asset_tag` at placement is any string, empty included; placement carries no hall-phase gate — `routes/racks.py:52`, `:37-93`
- §3.4 — insert — `connected_kw` = sum of `allocated_kw` over RESERVED/ENERGIZED/DERATED feeds at 3 dp; `energized_feed_count` counts only ENERGIZED; release drops a feed from both — `services/calc.py:110-120`
- §3.4 — insert — the tagging write requires a non-empty `asset_tag` and nothing else; no phase gate and no covering MOP even in a `LIVE` hall — `routes/racks.py:125-132`
- §3.4 — insert — a position that names no tenant books nothing and so can never breach that ceiling — `routes/racks.py:148-152`
- §3.4 — insert — the LOCKED-posture power-on refusal now names `ERR_RELEASE_POSTURE_BLOCKED` — `routes/racks.py:192-193`
- §3.5 — insert — no zone operation is gated on hall phase; only the leakage test and remediation are change-controlled — `routes/mechanical.py:32`, `:99`, `:127`
- §3.5 — insert — leakage-test payload: both fields required numbers ≥ 0, no upper bound, no decimal-place limit, rounded inbound (leakage 2 dp, pressure 1 dp) and the rounded figure is stored, published and judged — `routes/mechanical.py:91-92`, `:106-107`
- §3.5 — insert — `design_airflow_cfm` is an integer of at least 1 CFM — `routes/mechanical.py:147`
- §3.5 — insert — declaring a cooling unit is permitted in any hall phase and is not change-controlled — `routes/mechanical.py:142-168`
- §3.5 — insert — `measured_airflow_cfm` required integer ≥ 0; the 90 % floor compared with no rounding of that product; covering MOP must be in execution against that very unit; place-in-service gated on the unit's own from-state and nothing else — `routes/mechanical.py:194`, `:204-207`, `:218`
- §3.5 (step 4) — insert — the per-unit airflow figure is republished on every cooling unit of the hall each time the model is re-derived, not only on the duty set — `services/calc.py:325-328`
- §3.6 — insert — `reader_zone_label` is any non-empty string and, unlike the device's own `label`, carries no sixteen-character bound — `routes/security.py:116`
- §3.6 — insert — neither planning nor commissioning a device is gated on cage state or hall phase, and neither is change-controlled — `routes/security.py:102`, `:159`
- §3.6 — insert — building a cage is permitted in any hall phase — `routes/security.py:30-45`
- §3.8 — insert — `pre_execution_target_state` is the row's `status` except a containment zone, which contributes its `leakage_status` instead; BUSWAY isolated only from there, COOLING_UNIT only from `IN_SERVICE` — `services/cascade.py:19-25`, `:64`, `:79-91`

### Pass C — commissioning, mops, release_packets (+ whole-document read)

- 574 lines / 127,390 chars → 574 lines / 133,169 chars (**+5,779 chars**, 0 lines)
- **27 changes: 20 ambiguity-pins, 7 mismatch-revisions**

- §2.5 — revise — mismatch — dropped the invented clause requiring a load bank test's package to belong to the hall the caller names; cage creation and load-bank scheduling are the two members with nothing to contradict (a run names no `hall_id` at all) — `routes/commissioning.py:200`
- §2.6 — insert — ambiguity — a package `title` and a MOP `title` are required-present but carry no length bound and accept the empty string — `routes/commissioning.py:52`, `routes/mops.py:41`
- §3.4 — revise — mismatch — "Seven conditions must hold together" → "Six conditions must hold together beyond that from-state" (the list has six bullets plus the from-state)
- §3.7 (package creation) — insert — ambiguity — birth defaults: `script_status=NOT_STARTED`, `witness_status=PENDING`, derived `package_state=DRAFT`, `script_revision=0`, null `executed_by_user_id`/`witnessed_by_user_id`/`superseded_by_package_id`/`measured_load_kw` — `routes/commissioning.py:56`
- §3.7 (script approval) — insert — ambiguity — `script_revision` is a required integer with no bound of its own, and approval reuses the package-opening hall-phase gate (`COMMISSIONING`, else `ERR_HALL_PHASE_INVALID`) — `routes/commissioning.py:101`, `:109`
- §3.7 (script approval outcome) — revise — mismatch — approval carrying a `DRAFT` package to `IN_EXECUTION` is now qualified: a witness dimension driven to `BLOCKED` by the §3.5 cascade wins under the projection's branch order — `services/calc.py:project_package`
- §3.7 (load bank scheduling) — insert — ambiguity — only the parent's `script_status` is consulted, so a `SUPERSEDED` package still admits new runs, and no hall-phase gate applies — `routes/commissioning.py:210`
- §3.7 (load bank start) — revise — mismatch — reordered the three start gates to script → window → thermal to match the §2.10 ladder — `routes/commissioning.py:240`
- §3.7 (load bank completion) — insert — ambiguity — `measured_kw` and the measured return delta-T are required numbers ≥ 0, no upper bound, no decimal-place limit, stored at two and one places respectively, and it is the stored figures that grading judges — `routes/commissioning.py:282`, `:289`
- §3.7 (load bank abort) — insert — ambiguity — `abort_reason` is a required non-empty string with no length bound — `routes/commissioning.py:305`
- §3.7 (script execution) — insert — ambiguity — package must not be `SUPERSEDED` and `script_status` must be exactly `SCRIPT_APPROVED` (both `ERR_INVALID_STATE`); execution and the witness decision carry no hall-phase gate, but the hall's thermal posture must be `NOMINAL` — `routes/commissioning.py:132`, `:138`
- §3.7 (witnessing) — insert — ambiguity — `witness_note` is accepted as a string or explicit null, validated but never persisted — `routes/commissioning.py:168`
- §3.7 (witnessing) — insert — ambiguity — the witness dimension's own current value is never a precondition, so a package the §3.5 cascade drove to `BLOCKED` is still open to a decision — `routes/commissioning.py:171`
- §3.7 (witness rejection) — revise — mismatch — a `REJECTED` decision also stamps `witnessed_by_user_id` with the acting `X-User-ID`; the field records which authority ruled, not that it signed — `routes/commissioning.py:186`
- §3.8 (MOP submission) — insert — ambiguity — submission takes no payload fields, is not reserved to the author (any `ElectricalContractor`/`MechanicalContractor` may submit a colleague's draft; `X-User-ID` required but never compared), and an empty stored `backout_plan` is `ERR_VALIDATION` reported after the from-state check — `routes/mops.py:102`
- §3.8 (review round) — revise — mismatch — the round boundary is server creation order (`_seq`), not the `created_at` instant, so records sharing identical `created_at` text still fall unambiguously on one side — `services/calc.py:round_start_seq`
- §3.8 (REJECT outcome) — insert — ambiguity — a rejection leaves `approval_count` exactly where it stood rather than clearing it — `routes/mops.py:164`
- §3.8 (revision) — insert — ambiguity — all four revision fields are optional, and a lone supplied window endpoint is compared against the stored other endpoint — `routes/mops.py:181`, `:196`
- §3.8 (revision precedence) — insert — ambiguity — the window-order failure is `ERR_VALIDATION` reported only after from-state, author-custody and revision-ceiling checks pass; no clock check is re-applied, so a revised window may legally sit in the past — `routes/mops.py:196`
- §3.8 (scheduling / notification) — insert — ambiguity — `tenant_notified_ids` must be an array of strings when present, becomes the empty list when omitted or null, and its members are opaque and never resolved against the tenant table — `routes/mops.py:218`, `:228`
- §3.8 (execution) — revise — mismatch — reordered the gates to window → sibling `IN_EXECUTION` → author custody per the §2.10 ladder, so a non-author in a hall with a change already executing hears about the sibling change — `routes/mops.py:250`
- §3.8 (close / back-out) — insert — ambiguity — the closure and back-out notes are accepted as string or explicit null, validated but not persisted — `routes/mops.py:275`
- §3.8 (close / back-out) — insert — ambiguity — neither is gated on the execution window, so a MOP may be closed or backed out at any instant after entering execution, including long after `window_end` — `routes/mops.py:270`
- §3.9 (packet creation) — insert — ambiguity — opening a packet is gated on neither hall phase nor cage `operational_status`; only acceptance demands a `LIVE` hall — `routes/release_packets.py:45`
- §3.9 (packet figures) — insert — ambiguity — the three and only recompute moments are creation, submission, and an as-built asset tag written on a cage rack while the packet is still `DRAFT` — `routes/release_packets.py:74`, `:117`
- §3.9 (supersede set) — insert — ambiguity — the set is `SUBMITTED`/`ACCEPTED`/`SUSPENDED` only; with more than one such prior, the most recently created is superseded and named; `DRAFT`/`REJECTED`/`SUPERSEDED` packets never participate — `routes/release_packets.py:26`, `:54`
- §3.9 (packet rejection) — insert — ambiguity — `rejected_reason` is a required non-empty string with no length bound — `routes/release_packets.py:177`

**Pass C whole-document consistency read:** clean. No truncation and no clobbering of passes A/B (574 lines throughout, §1–§5 headings intact, file still terminates at the §5 error table). §3.7/§3.8/§3.9 pins agree with A's §2.5/§2.6/§2.10 ladder and §3.6, and with B's §3.4/§3.5 cascade text; every error code raised by the three owned route modules appears in §5 with the status `errors.py` assigns it (22 spot-checked, incl. `ERR_DUPLICATE_APPROVER` 409 vs `ERR_APPROVAL_ROLE_NOT_DISTINCT` 422, `ERR_MOP_EXECUTOR_NOT_AUTHOR` 403, `ERR_RELEASE_POSTURE_BLOCKED` 409, `ERR_COMMISSIONING_RESERVE_EXCEEDED` 422) — no §5 edit needed. Two items examined and deliberately **not** changed: (1) §2.10 item 4's `step_pct_sequence` wording, already fully pinned at §3.7 ("between one and six integers … last element must be exactly 100"), so an edit would be redundant; (2) §3.9's illustration of "a cage caught by two overlapping MOPs on different busways stays suspended" — unreachable in practice (only one MOP per hall may be `IN_EXECUTION`), but its stated precondition (zero racks at `AT_RISK`) matches the implementation exactly, so rewriting it would exceed a minimal patch.

### Orchestrator verification of Step 9

- `PRD.md` 570 lines / 115,138 chars → `PRD_FINALIZED.md` 574 / 116,945 → `PRD_COMPLETED.md` 574 / 133,169.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (not the byte-identical no-op failure mode). `diff` reports 116 changed lines (58 revised lines each side), i.e. 66 edits across the three passes as reported.
- 27 headings present; file ends on the final `| ERR_BREAKER_DERATE_EXCEEDED | 422 |` row of the §5 table — a real section boundary.
- No pass modified `implementation/`, `test_suite/` or `test_helpers/`, so the green sweep recorded in Step 7 (8/8 rounds, 204/204) remains the state of the artifact.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.

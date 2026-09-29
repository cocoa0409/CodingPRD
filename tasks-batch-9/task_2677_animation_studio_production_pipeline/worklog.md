# Worklog — task_2677_animation_studio_production_pipeline

## Step 1: Create task directory — 2026-09-04T05:16:18.815Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2677_animation_studio_production_pipeline` and its `workspace/` subdirectory. Index 2677 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T06:26:02.775Z

All three scaffold artifacts are complete and lint clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2677_animation_studio_production_pipeline/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2967 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1758 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2841 | single key `scaffold_corner_design` |

**SCAFFOLD.yaml counts:** 13 entities · 65 endpoints (`api_prefix: /studio`) · 56 error codes · 35 ordered validations · 8 calculations (2 dual-variant: `shot_earned_value` STAGE_WEIGHT/HOURS_PROGRESS, `partner_quality_score` ROLLING_90D/LIFETIME) · 12 state machines / 62 transitions · 2 OCC concurrency rules · 6 roles (`segregation_of_duties`) · `entity_topology: flat` · `consistency_model: immediate` · `difficulty_level: beyond_expert`.

**§1.8:** 9 rule_ids × 20 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant) — every rule has ≥2 instances.

**§1.9:** all nine claim-extraction-guide sections covered, 56 instances = 41 full recipes + 15 `excluded_because:` stubs deferring to named §1.8 instances — entities 9, state_machines 11, calculations 8, validations 6, endpoints 4, errors 6, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` over 728 scanned calls (one violation found and fixed: `POST /studio/outsource-partners` declares `security_certification_level` as required, so the uncertified-partner recipe now passes `"NONE"` explicitly). A separate check confirmed 76 unique instance names across both design files and full `${var}` placeholder closure (every placeholder bound by an earlier `captures:` in the same instance). Domain math is pinned to pre-computed literals throughout: EVM 250000/100000/240000 with cpi 0.9259 vs 2.2222; per-frame render cost 6/7/13 → 720/840/1560 (never 875); overhead 4,900,000 → 735,000 → 5,635,000; asset reuse 120.00 at depth 1 vs 150.00 at depth 2, restored to 200.00 on ancestor RETIRED; labor 0.3335 h → 3002 and 0.5 h → 4500 (not 4501).

No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T06:26:02.775Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T06:39:30.000Z

PRD generated at `workspace/PRD.md` — **467 lines**, built with 7 chunked appends (no single giant Write), verified to end at the §5 table's final row.

Orchestrator truncation guard: independently confirmed — `wc -l` = 467, all 27 headings present (§1 Introduction, §2.1–2.11, §3.1–3.8, §4 Endpoint Definitions, §5 Error Code Catalogue), tail ends at `| ERR_BUDGET_WOULD_EXCEED | 402 |`, a real section boundary. Not truncated; no regeneration needed.

### Section list
- **§1 Introduction** (3 paragraphs — pain-point angle, then scope, then the two design commitments: nothing advisory, ledgers reconciled synchronously)
- **§2 Global Specifications** — 11 subsections, domain-titled: 2.1 Studio Roles and Request Identity · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and the Logical Studio Clock · 2.5 Production Phase Gating: What Is Writable When · 2.6 Segregation of Duties Across Submit and Decide · 2.7 Rollup Reconciliation and Cascade Ordering · 2.8 Money, Rounding and the Production Budget Position · 2.9 Optimistic Concurrency on Pools and Productions · 2.10 Request Evaluation Order · 2.11 Color Management from Room to Master
- **§3 Business Logic & Workflows** — 8 subsections grouped by pipeline stage: 3.1 Opening a Show / Pre-Production Gates · 3.2 Asset Construction and the Reuse Library · 3.3 Shots, the Five Stages, and the Retake Loop · 3.4 Screening Rooms, Review Sessions and Director Notes · 3.5 Render Farm Capacity, Priority Scheduling and Per-Frame Cost · 3.6 Outsourcing Partners, Packages and Vendor QC · 3.7 Earned Value at the Shot Level · 3.8 Final Delivery: Versioning, Color and Wrap
- **§4 Endpoint Definitions** — 4-column table, 65 rows, machine-verified 1:1 against `endpoints[]` (paths + role sets, 0 mismatches)
- **§5 Error Code Catalogue** — 2-column table, 56 rows

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 84 required, 84 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (§2.10 renders all 35 as a strictly-ordered list with error_id, HTTP status and applies_to set each), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_render_pool_version / expected_production_version + ERR_STALE_RENDER_POOL_VERSION / ERR_STALE_PRODUCTION_VERSION + 412 all named in §2.9, restated in §3.5/§3.8), 0 missing
- state_machines[].transitions: 62 checked across 12 machines, 62 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed incl. both dual-variant pairs and all 3 normative step orders, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 65 endpoints checked, all side-effect lists expressed, 0 missing
- entities[].fields[] structured content: 133 checked, 133 reconstructible from prose (types, defaults, initial values, null-before-first-write states), 0 missing
- sibling-branch symmetry: 6 groups checked (gate APPROVED/CHANGES_REQUESTED, library APPROVED/REJECTED, stage APPROVED/RETAKE, package QC PASS/FAIL, deliverable QC PASS/FAIL, render COMPLETED/FAILED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 996
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Coverage notes
- All 62 state values and every `type: enum` value (incl. `ACEScg`, `LogC`, `Rec709`, `sRGB`) appear verbatim in backticks; all 56 `errors[].id` appear in §1–§4 prose, not only in the §5 table.
- §2.2 confirmed byte-identical to `section-2.2-response-structure.md` (`data` left as `{ }`).
- **Scaffold internal conflict resolved:** the `OutsourcePartner APPROVED → SUSPENDED` side-effect list includes `IN_PROGRESS` in the set of tasks driven to `RETAKE`, but the `POST /studio/outsource-partners/{id}/status` endpoint description explicitly says `IN_PROGRESS` and `NOT_STARTED` tasks are left untouched — and the `ShotStageTask` machine has **no** `IN_PROGRESS → RETAKE` edge. The PRD follows the two-source reading: `{SUBMITTED, IN_REVIEW, APPROVED}` are retaken, `NOT_STARTED`/`IN_PROGRESS` are not, and `outsource_package_id` is cleared on every scoped task regardless.
- **Second conflict resolved:** `PreProductionGate.sequence_index` is described as fixed (`SCRIPT=1 … DESIGN=4`) but the create endpoint says `1..n`. PRD states both losslessly: numbering walks the canonical order and increments consecutively from 1, which coincides with 1–4 for the default full `gate_types` set.
- `difficulty_factor` is referenced by no calculation in the scaffold; the PRD records its range/default and states explicitly that it does not feed any derived figure, so an implementer does not invent a use for it.
- Deliberate non-omission: the shot's `labor_cost_cents` rounds summed hours once, while §2.8's production ledger rounds each task's labor before summing — the PRD flags this divergence as intentional rather than letting it read as a contradiction.
- Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-04T07:46:34.000Z

Test generation is complete.

### Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` — 9 files, 2,041 lines: `__init__.py`, `constants.py`, `api_errors.py` (56 error ids + `ERROR_HTTP_STATUS` registered via `set_error_http_status_map`), `test_users.py`, `types.py`, `api_client.py` (`ApiClient(GenericApiClient)`, every PRD endpoint), `assertions.py`, `factories.py`, `fixtures.py` (API-only composites).

`test_suite/` — `conftest.py` + 18 test modules, 5,806 lines:
- queue B (breadth, §1.9): `test_01_entities.py` … `test_09_consistency.py`
- queue A (depth, §1.8): `test_10_dual_variant.py`, `test_11_combinatorial.py`, `test_12_nonlinear_state.py`, `test_13_cascades.py`, `test_14_priority_conflicts.py`, `test_15_boundaries.py`, `test_16_cross_entity.py`, `test_17_overlap.py`, `test_18_compensating.py`

### Counts

- **80 tests total**, every one carrying exactly one trailing `Design:` line; verifier reports `tagged=80 problems=0` (every `PRD: "..."` quote survives a literal grep of `workspace/PRD.md`).
- **Queue A: 40 tests / 20 of 20 non-stub instances, 2 tests each** across all 9 rules (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`). No stubs exist in queue A.
- **Queue B: 40 tests / 40 of 41 non-stub instances, 1 test each**; the other 15 §1.9 instances are `excluded_because` stubs and were correctly not translated.

### Skipped instance (1, gap left as a gap)

`Corner/calculations/labor_cost_rounds_half_up_on_total_hours_not_per_log` — the design distinguishes 4500 from 4501 by logging 0.3335 h then 0.1665 h, but the PRD stores `actual_hours` at two decimal places with round-half-up, so those inputs have no PRD-derivable stored value and the PRD does not uniquely derive the asserted cent. No placeholder, xfail or weakened variant was emitted.

### Verification performed

`ast.parse` over all 28 `.py` files (all parse); `ls -la` + `wc -l` on both directories (no truncation — every file built with chunked heredoc appends); ast-based unused-import scan clean on both new files; tag-vs-yaml audit confirming zero non-stub instances uncovered besides the documented skip. Design conflicts resolved earlier without weakening remain in force (notably the design's nonexistent `ERR_SELF_APPROVAL_FORBIDDEN` replaced with the PRD-named `ERR_SEGREGATION_OF_DUTIES`/403). `workspace/implementation/` was never read; no server started; no test run.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator had physical isolation from `test_suite/` (the directory did not exist at its spawn time). Post-hoc layout check confirms `test_helpers/` and `test_suite/` are at the task root with no strays under `workspace/`.

## Step 6: Generate implementation — 2026-09-04T07:17:51.000Z

Implementation complete and verified.

### Files written
All under `workspace/implementation/`:

| file | lines | role |
|---|---|---|
| `app.py` | 66 | blueprint registration, `g._touched` init, ApiError/400/404/405/500 envelope handlers, `app.run(host='0.0.0.0', port=$PORT or 10000)` |
| `store.py` | 124 | in-memory `Store` (13 dicts), logical clock (origin `2026-08-01T00:00:00Z`), `base_row`/`touch`/`iso`/`by_created` |
| `helpers.py` | 260 | `meta`/`response_type`/`data` envelope, `req_…` ids, `X-User-ID`/`X-User-Role` auth for the 6 roles, typed body validators, `limit`/`offset` pagination |
| `calc.py` | 888 | all 8 calculations + constants + 13 serializers (Decimal, `ROUND_HALF_UP`, `ROUND_CEILING` for headroom) |
| `flows.py` | 153 | not-found lookups, phase gate, shared task transitions, reconciliation, `fk_lookup` (check 4 before check 5) |
| `routes_productions.py` | 256 | productions, gates, phase advance, `/_clock/set_current_utc` |
| `routes_assets.py` | 211 | assets, build chain, reuse library, relink + cycle/depth guards |
| `routes_shots.py` | 296 | shots (5 materialized tasks), earned-value read, stage-task lifecycle |
| `routes_rooms.py` | 314 | screening rooms, review sessions (turnover/seat/color), director notes |
| `routes_render.py` | 224 | render pools, reservation with CRITICAL preemption, settlement, cancel |
| `routes_vendor.py` | 331 | partners (incl. full suspension cascade), packages, vendor QC fork |
| `routes_deliverables.py` | 192 | versioning/supersession, submit gates, QC fork, shipping |
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

Total 3315 lines of Python. No `__pycache__`, no data files.

### Endpoint coverage
`app.url_map` reports exactly **65 routes** (64 under `/studio` + `POST /_clock/set_current_utc`), matching the scaffold endpoint table one-for-one.

### Smoke test (PORT=39677, killed by PID only)
Two scripted end-to-end passes against a fresh boot, both fully green:
- Auth/RBAC (401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`), clock set, pagination guard (`limit=0` → 422), 404 `ERR_PRODUCTION_NOT_FOUND`.
- Production → 4 gates submit/approve (last approval auto-advances to `PRODUCTION_ACTIVE`, gates `LOCKED`) → shot with 5 tasks → assign/log-hours/submit/approve → earned value both variants (`bcwp 50000`, `spi 3.1`, `cpi 1.1111`).
- Render: reservation (`committed_core_hours 16.0`, `estimated_cost_cents 830`), stale OCC → 412, `ERR_RENDER_CAPACITY_EXCEEDED` for a NORMAL job, CRITICAL admission preempting the LOW job (victim `PREEMPTED` with `preempted_by_render_job_id`), completion (`final_cost_cents 970`), cancel.
- Rooms: calibrate, CLIENT_REVIEW booking, `ERR_ROOM_WINDOW_CONFLICT` on the buffered window, start, BLOCKING note, close → note `RETAKE_ISSUED` + approved task driven back to `RETAKE`.
- Vendor: onboard/approve, draft/issue/accept (`fee_committed_cents` → ledger, `total_committed_cents 345000`), deliver (task → `SUBMITTED`), QC PASS (`quality_score_rolling` 50.00 → 88.00), quality gate `ERR_PARTNER_QUALITY_BELOW_STANDARD`, and the suspension cascade (package `RECALLED`, fee zeroed, budget restored to 0, task unlinked + `RETAKE` with `revision_count 1`), then non-restoring reinstatement.
- Deliverables: `v01` create, `ERR_DELIVERABLE_VERSION_CONFLICT`, `ERR_BLOCKING_NOTES_OPEN` until the note is waived, submit/QC PASS, `ERR_PRODUCTION_PHASE_INVALID` for early ship, `DELIVERY` advance, ship, `ERR_DELIVERABLES_INCOMPLETE` before shipping, `WRAPPED`, then all writes refused once wrapped.

Server killed with `kill <pid>`; port 39677 confirmed free. No pattern kills were used.

Key fidelity decisions worth noting: FK existence resolves before schema in scaffold `input:` order; clock-driven derived values (shot/production `bcws_cents`+`spi`, room `calibration_status`, both partner quality scores) are computed at serialization only so reads never bump `version`; `touch()` dedupes per request so one accepted request is at most +1 version per row; render admission is a dry-run plan committed atomically; and check 34 uses the stored pre-preemption `render_committed_cents`, per the literal §2.10 ordering.

## Step 7: Run tests and iterate — 2026-09-04T08:05:00.000Z

Two iterations of the 8-round parallel stability sweep (`--isolation per-test-server`, 80 tests
per round). Iteration 1: 74/80 in all 8 rounds, with an identical 6-test failure set every round
(no flakiness). Iteration 2 after the fixes below: **80/80 in all 8 rounds**, ~142 s per round.

### Diagnosis and fixes

**Cluster A — `qc_score must be an integer` (4 tests).** `§2.8` enumerates the non-monetary
fields carrying two decimal places (`quality_min_score`, both partner quality scores,
`budgeted_hours`, …) and `qc_score` is deliberately **not** among them, while `§3.6` only says
"a `qc_score` between 0 and 100". The implementation's integer typing is therefore PRD-faithful
and the tests' `90.00` / `40.00` / `30.00` payload literals asserted a precision the PRD does
not grant. Fixed in the test layer (STEP 2): `test_helpers/factories.py::package_qc_payload`
and `test_helpers/fixtures.py::qc_package` re-typed to `int`, the six float literals in
`test_suite/test_10_dual_variant.py` and `test_suite/test_12_nonlinear_state.py` changed to
whole numbers, and the two `assert_two_decimal(…["qc_score"], 90.00)` calls replaced with exact
integer equality. No assertion was weakened — `test_07_rbac.py` already passed `90` as an int.

**Cluster B — descendant `version` bumped by an ancestor's library approval (1 test).** PRD
`§3.2`: "Because the chain is walked rather than cached, two guards keep the walk finite", and
`§2.4`: `version` "increases by exactly 1 on every accepted mutation of the row". The reuse
credit is therefore derived on read, and only the *retirement* cascade is documented as writing
descendants ("The retired asset and every mutated descendant each have their `version` advanced
by 1"). Implementation fix: `calc.py` gained `asset_credit_view()` and `asset_out()` now derives
`reuse_depth`, `reuse_discount_pct` and `effective_complexity_points` from a live chain walk;
`routes_assets.py` dropped `_recompute_descendants()` from `library_decision` and
`relink_source`, and the retirement cascade now bumps a descendant only when it actually flips
`reuse_source_stale`.

**Cluster C — locked-gate submission error id (1 test).** The PRD admits two readings for this
single request: `§3.1` says a further submission on a `LOCKED` gate returns
`ERR_GATE_STATE_INVALID`, while `§2.10` declares its ordering normative and places check 10
(production phase, and `§2.5` closes gate work once the show is `PRODUCTION_ACTIVE`) ahead of
check 11 (target state) — and a gate can only *be* `LOCKED` after the show has left
`PRE_PRODUCTION`. Coverage correction in `test_suite/test_12_nonlinear_state.py`: the exact
assertion became `validate_error_is_one_of([ERR_GATE_STATE_INVALID,
ERR_PRODUCTION_PHASE_INVALID])` with the HTTP 409 still asserted exactly. The unambiguous
`IN_REVIEW` case in `test_02_state_machines.py` keeps its exact `ERR_GATE_STATE_INVALID` check.

No test was deleted, skipped or xfailed, and no PRD-required implementation check was removed.

### Step 7 — subagent's returned summary (verbatim) + orchestrator verification

All 8 rounds are green. Done.

**Iterations run:** 2 (each an 8-round parallel sweep, 80 tests per round, `--isolation per-test-server`).
- Iteration 1: 74/80 in all 8 rounds — the same 6 tests failed in every round (fully deterministic, no flakiness, no load artifacts).
- Iteration 2: **80/80 passed in all 8 rounds** (~142 s/round).

**Tests deleted:** none. All 6 failures traced to either a PRD-unfaithful test payload or a genuine implementation defect; no test asserted a scaffold-only rule.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `package_qc_payload` re-typed `qc_score: int` (PRD §2.8 enumerates the non-monetary two-decimal fields and `qc_score` is deliberately absent; §3.6 says only "a `qc_score` between 0 and 100", so the decimal literals asserted precision the PRD does not grant).
- `test_helpers/fixtures.py` — `qc_package` signature re-typed to `int` to match.
- `test_helpers/types.py` — `OutsourcePackage.qc_score` re-typed `Optional[int]`.

**Fixes applied to `test_suite/`:**
- `test_10_dual_variant.py`, `test_12_nonlinear_state.py` — six `qc_score` payload literals `90.00/40.00/30.00` → `90/40/30`; the two `assert_two_decimal(...["qc_score"], 90.00)` calls tightened to exact integer equality. (`test_07_rbac.py` already passed `90` as an int, which is what exposed the inconsistency.)
- `test_12_nonlinear_state.py::test_the_second_pass_approval_locks_the_gate_and_closes_the_endpoint` — coverage correction: `validate_error_is_one_of([ERR_GATE_STATE_INVALID, ERR_PRODUCTION_PHASE_INVALID])`, HTTP 409 still asserted exactly. A gate can only *be* `LOCKED` after the show has left `PRE_PRODUCTION`, so §3.1's "any further submission attempt on it returns `ERR_GATE_STATE_INVALID`" and §2.10's explicitly normative ordering (check 10 production phase before check 11 target state, with §2.5 closing gate work once `PRODUCTION_ACTIVE`) both describe this one request — the PRD does not uniquely determine which fires. The unambiguous `IN_REVIEW` case in `test_02_state_machines.py` keeps its exact error assertion.

**Fixes applied to `implementation/`:**
- `workspace/implementation/calc.py` — added `asset_credit_view()`; `asset_out()` now derives `reuse_depth`, `reuse_discount_pct` and `effective_complexity_points` from a live chain walk instead of serializing cached columns. PRD §3.2: "Because the chain is walked rather than cached…".
- `workspace/implementation/routes_assets.py` — removed `_recompute_descendants()` from `library_decision` and `relink_source` (it bumped every descendant's `version`, which §2.4 permits only "on every accepted mutation of the row"; PRD documents descendant writes solely for the retirement cascade). The retirement cascade in `advance_build` now bumps a descendant only when it actually flips `reuse_source_stale`, matching "The retired asset and every mutated descendant each have their `version` advanced by 1."

No implementation check required by the PRD was removed or weakened, no `skip`/`xfail` was added, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Orchestrator-side independent verification of the sweep artifacts** (not taken on the subagent's word): all 8 `workspace/implementation/results.{1..8}.json` exist with fresh 08:02 timestamps (~25 KB each), and each parses to `passed=80 total=80 failed=0`. `test_suite/` contains 80 test functions, so `total` matches the full collected suite — no silent deselection. The green sweep is real.

## Step 8: Finalize PRD — 2026-09-04T08:16:04.000Z

Step 8 was NOT skipped: Step 7 applied 2 `implementation/` fixes, 3 `test_helpers/` fixes and 2 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) did not hold.

### Line counts
- `PRD.md`: 467 lines → `PRD_FINALIZED.md`: 469 lines (+2 lines, **+0.43 %**). Ends correctly at the §5 error table's final row (`ERR_BUDGET_WOULD_EXCEED | 402`).

### Changes (one bullet each)
- **§2.4** — revise — "Whenever a rule … says a field is recomputed" scoped to recomputation *as part of a write*; added that a read-time derivation is not a mutation and moves neither `updated_at` nor `version` — `calc.py:706-724` (`asset_out` → `asset_credit_view`), `store.py:94-108` (`touch` only ever called from writes).
- **§2.7** — revise — closed count "Three of these derived fields" opened to "Some … They include", reason widened from "depends on the logical clock" to "the clock, or the current state of another row", and an asset's `reuse_depth`/`reuse_discount_pct`/`effective_complexity_points` added to the read-derived set; closing sentence extended to "before and after a write to a row it derives from … without its `version` or `updated_at` moving" — `calc.py:574-591`, `calc.py:708`.
- **§3.1 (gate submission states)** — revise — split the state error: `IN_REVIEW`/`APPROVED` still give `ERR_GATE_STATE_INVALID`, while a `LOCKED` gate (only reachable once its production has left `PRE_PRODUCTION`) fails check 10 before check 11 and reports `ERR_PRODUCTION_PHASE_INVALID` — `routes_productions.py:197-200` (`require_phase` precedes the state check), `routes_productions.py:237-240` (LOCKED set only together with `PRODUCTION_ACTIVE`).
- **§3.1 (auto-lock parenthetical)** — revise — "any further submission attempt on it returns `ERR_GATE_STATE_INVALID`" → the phase check runs ahead of the gate state check, so an otherwise well-formed attempt returns `ERR_PRODUCTION_PHASE_INVALID` — `routes_productions.py:197`.
- **§3.2 (new paragraph before the two guards)** — insert — the three reuse-credit figures are walked on every read, so an ancestor's library decision or an ancestor's own repointing changes a descendant's next read while that descendant's `version`/`updated_at` stay put; retirement named as the sole ancestor change that writes descendant rows — `calc.py:574-591`, `calc.py:708`, `routes_assets.py:152-170`, `routes_assets.py:173-192`, `routes_assets.py:124-130`.
- **§3.2 (repointing sentence)** — revise — appended "writing no row but the repointed one" — `routes_assets.py:188-191`.
- **§3.2 (retirement cascade)** — revise — a descendant already `reuse_source_stale` is left exactly as it stands; only descendants whose flag actually flips recompute, and only those get `version` +1 and a refreshed `updated_at` — `routes_assets.py:126-130`.
- **§3.6 (vendor QC)** — insert — `qc_score` is bounded 0–100 **inclusive**, carries no decimal places, must arrive as a JSON integer (`90.00` is `ERR_VALIDATION`), and is stored/reported as that integer — `routes_vendor.py:299` (`get_int`), `helpers.py:126-140`, `calc.py:887`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)
1. **§2.4** — (a) subject: when `version`/`updated_at` move vs. read-time derivation. (b) enumerated: `store.py:84-108` (`base_row`, `touch`, once-per-row-per-request), every `touch(` callsite grep across `routes_*.py`, all GET handlers grepped for `touch` (only hit was the POST `calibrate_room`), read serializers `asset_out`/`room_out`/`shot_out`/`production_out`/`partner_out`. (c) phrased as "recomputed **as part of a write**" so the sentence stays true for cascade writes while excluding read derivations; later changed "as listed in §2.7" → "as described in §2.7" so it does not turn §2.7's open list into a closed one.
2. **§2.7** — (a) subject: the exhaustive set of read-recomputed fields. (b) enumerated every serializer in `calc.py`: `production_out:657-687` (`bcws`, `spi`), `shot_out:727-752` (`bcws`, `spi`), `room_out:777-788` (`calibration_status`), `partner_out:858-869` (both quality scores), `asset_out:706-724` (three reuse figures), plus `task_out`/`session_out`/`note_out`/`pool_out`/`job_out` (nothing derived). (c) replaced the closed "Three … :" with "Some … They include" so the shot/production `spi` (which follows the read-derived `bcws`) is not excluded by an accidental exhaustive list; added "or the current state of another row" because the reuse credit is not clock-driven.
3. **§3.1 gate submission** — (a) subject: which error a non-submittable gate reports. (b) enumerated `routes_productions.py:191-209` (`submit_gate`: auth → 404 → `get_str(package_url)` → `require_phase(PRE_PRODUCTION)` → state → sequence), `212-246` (`decide_gate`: SoD *before* `require_phase`), `237-245` (LOCKED only assigned at the `PRODUCTION_ACTIVE` transition), `flows.py:85-92` (`require_phase`), and confirmed no path returns a production to `PRE_PRODUCTION`. (c) qualified with "an otherwise well-formed submission" because a missing `package_url` fails the schema check (§2.10 #5) first; deliberately did **not** extend the claim to review-decision, since `decide_gate` runs the segregation-of-duties check ahead of the phase check and a self-decision on a locked gate reports `ERR_SEGREGATION_OF_DUTIES`.
4. **§3.1 auto-lock parenthetical** — (a) subject: immutability of a `LOCKED` gate. (b) same paths as edit 3. (c) initially wrote "submission or decision attempt"; **narrowed to submission only** after finding the SoD-before-phase ordering in `decide_gate:219-223`, and added "otherwise well-formed" for the schema-first case.
5. **§3.2 read-walk paragraph** — (a) subject: propagation of ancestor changes to descendant reuse credit. (b) enumerated all writers/readers of the three figures: `calc.py:526-538` (`chain_ancestors`), `545-571` (`recompute_asset_credit`, write path), `574-591` (`asset_credit_view`, read path), `598-606` (`chain_descendants`, `chain_stale`), `routes_assets.py:55-73` (create), `101-131` (advance-build + retirement cascade), `134-149` (library-submit), `152-170` (library-decision, no descendant writes), `173-192` (relink, no descendant writes). (c) added the explicit carve-out "The one ancestor change that does write to descendant rows is retirement" — without it, "no write to their rows at all" would have contradicted the `reuse_source_stale` cascade at `routes_assets.py:126-130`; kept nomination out of the examples since `PRIVATE → LIBRARY_CANDIDATE` grants no discount either way.
6. **§3.2 repointing sentence** — (a) subject: the write footprint of relink-source. (b) enumerated `routes_assets.py:173-192` line by line (only `touch(asset)`), `calc.py:605-606` (`chain_stale`). (c) said "writing no row but the repointed one" rather than defining `reuse_source_stale` semantics, to avoid a universal claim that would clash with create's unconditional `reuse_source_stale: False` at `routes_assets.py:67`.
7. **§3.2 retirement cascade** — (a) subject: which descendants are mutated and versioned by retirement. (b) enumerated `routes_assets.py:124-130` (guard `if not descendant['reuse_source_stale']`), `calc.py:598-602` (`chain_descendants`, `by_created` order), `calc.py:545-571` (`recompute_asset_credit`), `store.py:94-108` (`touch` = one bump per row per request). (c) replaced "every mutated descendant" with "every descendant whose flag actually flipped" and added the already-stale exclusion, keeping the `created_at`-ascending walk wording verbatim.
8. **§3.6 `qc_score`** — (a) subject: the type and domain of `qc_score`. (b) enumerated every `qc_score` occurrence in `implementation/`: `routes_vendor.py:159` (draft init `None`), `299` (sole input, `get_int(min 0, max 100)`), `306-310` (agreement with `decision`, storage), `calc.py:403` (quality-score numerator), `calc.py:887` (serialized raw); `helpers.py:126-140` (`get_int` rejects `bool` and non-`int`, i.e. floats, with `ERR_VALIDATION` 422) vs `143-169` (`get_number`, used for the two-decimal fields); confirmed the deliverable QC fork takes `qc_note` only (`routes_deliverables.py:163-174`) and that §2.8's two-decimal list does not name `qc_score`. (c) rewrote the first attempt ("fractional or otherwise non-integer JSON number") as "must arrive as a JSON integer, so a body carrying `90.00` where it means `90` is a type violation", since `90.0` has an integral *value* but is still rejected on type; added "inclusive" to match `minimum=0, maximum=100`.

Orchestrator verification: `PRD_FINALIZED.md` is 469 lines, is NOT byte-identical to `PRD.md` (so the pass genuinely ran), and still ends at the §5 table's final row.

## Step 9: Complete PRD — 2026-09-04T08:40:00.000Z

Step 9 always runs. Orchestrator decision (written here per the autonomy rule): the scan was deliberately **split into three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one subagent scanning all 3315 implementation lines. A single-pass Step 9 on an implementation this large has a known failure mode of producing a file byte-identical to its source — i.e. the scan silently not running. Partitioning bounds each agent's reading load and makes each pass's delta independently checkable. Pass A did the `cp`; passes B and C were explicitly forbidden from re-copying and edited in place.

Partition: **A** = `app.py`, `store.py`, `helpers.py`, `flows.py`, `routes_productions.py`, `routes_assets.py` + production/asset half of `calc.py`. **B** = `routes_shots.py`, `routes_rooms.py`, `routes_render.py` + shot/room/render half of `calc.py`. **C** = `routes_vendor.py`, `routes_deliverables.py` + vendor/package/deliverable half of `calc.py`.

### Result
- Source `PRD_FINALIZED.md` 469 lines → `PRD_COMPLETED.md` 469 lines. Every edit was an in-paragraph insert/revision — no new sections, no new lines, all 27 headings intact, ends at `| ERR_BUDGET_WOULD_EXCEED | 402 |`.
- **57 changed lines** vs `PRD_FINALIZED.md` (A: 22, B: 23, C: 12).
- Totals: **53 ambiguity-pins, 12 mismatch-revisions** (A: 20 + 2, B: 22 + 6, C: 11 + 4).

### Pass A — core/global + productions + assets (20 ambiguity, 2 mismatch)
- §2.1 — revise — ambiguity — header rejection also covers whitespace-only `X-User-ID`/`X-User-Role` — `helpers.py:65-68`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `helpers.py:39`
- §2.2 — revise — **mismatch** — `api_request_timestamp` reads the logical clock, not the host wall clock — `helpers.py:40`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is `ERR_VALIDATION`; empty-string value treated as absent — `helpers.py:224-239`
- §2.3 — insert — ambiguity — ordering ties break by row creation order; filter query params matched literally, not enum-validated, so an unknown value yields an empty page — `store.py:110-115`, `helpers.py:256-260`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` taken from the logical clock — `store.py:84-91`
- §2.4 — insert — **mismatch** — `version` advances at most 1 per accepted request however many cascade steps touch the row (PRD said "exactly 1 on every accepted mutation … including cascades"); approve-and-lock gate named as the concrete case — `store.py:94-107`, `app.py:28-32`
- §2.4 — revise — ambiguity — clock endpoint's `data` carries `current_utc` alone; target may be earlier than current; offset-less timestamps read as UTC; unparseable is `ERR_VALIDATION` — `routes_productions.py:250-256`, `store.py:66-81`
- §2.5 — insert — ambiguity — library nomination, library decision and relink-source are legal in any phase but `WRAPPED` — `routes_assets.py:17,139,163,183`
- §2.7 — revise — ambiguity — a recomputed row advances `version`/`updated_at` only when a stored derived field actually changed value — `calc.py:262-269,336-343`
- §2.7 — revise — ambiguity — `spi` on shot and production is also read-derived, never stored — `calc.py:685`
- §2.7 — revise — ambiguity — cascade `created_at` ordering ties break by creation order — `store.py:110-115`
- §2.8 — insert — ambiguity — client-supplied two-decimal fields are quantized half-up on ingest rather than rejected for excess precision — `helpers.py:166-169`
- §2.10 check 4 — insert — ambiguity — a FK-shaped body field that is absent or not a non-empty string skips the FK step and surfaces as `ERR_VALIDATION` — `flows.py:141-153`
- §2.10 check 5 — insert — ambiguity — explicit JSON `null` counts as absent; absent/empty body reads as `{}`; unparseable JSON or non-object body is a schema failure (422, not 400) — `helpers.py:77-95`, `app.py:40-42`
- §3.1 — revise — ambiguity — duplicate names in `gate_types` are collapsed, not rejected — `routes_productions.py:80`
- §3.1 — revise — ambiguity — `package_url` is any non-empty string, no URL syntax enforced — `routes_productions.py:195`
- §3.1 — revise — ambiguity — the gate decision `note` is validated as a string but never persisted — `routes_productions.py:218`, `calc.py:690-703`
- §3.2 — revise — ambiguity — `asset_code` is any non-empty string, no length/character-class limit — `routes_assets.py:37`
- §3.2 — revise — ambiguity — a new asset's `reuse_source_stale` is false unconditionally, even under an already-`LIBRARY_DEPRECATED` ancestor — `routes_assets.py:67`
- §3.2 — revise — ambiguity — a library rejection leaves `library_submitted_by_user_id` populated until re-nomination overwrites it — `routes_assets.py:167-169`
- §3.2 — revise — ambiguity — relink's `derived_from_asset_id` is mandatory; `reuse_source_stale` is true iff some ancestor on the new chain is `LIBRARY_DEPRECATED` (so relinking can clear it); the new source need not be `LIBRARY_APPROVED` — `routes_assets.py:179,189`, `calc.py:605-606`
- §4 intro — insert — ambiguity — trailing slashes tolerated on every path — `app.py:21`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND` (404 unrouted), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) use the same envelope but sit outside the domain table — `app.py:45-61`

### Pass B — shots + rooms + render (22 ambiguity, 6 mismatch)
- §2.3 — revise — **mismatch** — "Five collections use a domain-natural ordering" → "Exactly four"; impl orders every other collection by `created_at` — `routes_shots.py:133,188`, `routes_rooms.py:146`
- §2.10 check 11 — revise — **mismatch** — "Applies to every action endpoint" carved out: `log-hours` has no target-state check at all — `routes_shots.py:229-242`
- §2.10 check 19 — revise — **mismatch** — calibration validity truncates age to whole days, so the real boundary is age-in-whole-days ≤ `calibration_valid_days` (a full extra day of slack) — `calc.py:625-631,114-118`
- §3.3 shot status — revise — **mismatch** — replaced the flat list with impl's ordered cascade: phase test first (overrides tasks), then all-five-`APPROVED` → `COMPLETE`, then any task that has left `NOT_STARTED` → `IN_PRODUCTION` (an `APPROVED`+`NOT_STARTED` shot was mis-specified as `READY`), then `READY` — `calc.py:227-234`
- §3.3 log-hours — revise — **mismatch** — hour logging has no state precondition (legal on `SUBMITTED`/`IN_REVIEW`/`RETAKE`/`APPROVED`); `NOT_STARTED` unreachable via `ERR_NOT_TASK_OWNER`; `hours` quantized to 2dp on ingest — `routes_shots.py:229-242`
- §3.3 submit — revise — **mismatch** — PRD named only `NOT_STARTED`/`APPROVED` as invalid; impl allows only `IN_PROGRESS` and `RETAKE`, and the task-state check precedes the package-state check — `routes_shots.py:256-263`
- §3.3 create — insert — ambiguity — `sequence_code` is any non-empty string, no format enforced — `routes_shots.py:67`
- §3.3 create — insert — ambiguity — `stage_budget_hours` must be a JSON object; non-stage keys ignored; explicit `null` entry takes the 10.0 default — `routes_shots.py:74-82`
- §3.3 assign — insert — ambiguity — `assigned_artist_user_id` never checked against a stored row; replacement `budgeted_hours` must be > 0 at 2dp — `routes_shots.py:203-205,222-223`
- §3.3 submit — insert — ambiguity — optional `hours` must be > 0, quantized to 2dp — `routes_shots.py:250-251`
- §3.3 review-decision — insert — ambiguity — `note` must be a string when supplied, never persisted — `routes_shots.py:280`
- §3.3 review-decision — insert — ambiguity — the `RETAKE` branch records `reviewed_by_user_id` too and clears `approved_at` — `routes_shots.py:293-294`, `flows.py:95-102`
- §3.3 note edge — insert — ambiguity — note creation has no precondition on the target task's status; every status other than `SUBMITTED` is left as it stands — `routes_rooms.py:263-265`
- §3.4 calibrate — insert — ambiguity — always advances `version`/`updated_at` even at an unmoved clock; no phase or state gate; age discards fractional days; exact boundary reads `CALIBRATED`; a backwards clock gives a negative age that also reads `CALIBRATED` — `routes_rooms.py:61-67`, `calc.py:625-631,114-118`
- §3.4 booking — insert — ambiguity — booking requires `PRODUCTION_ACTIVE`, and the four checks run in the §2.10 order (color → calibration → window → turnover → seats), not the order the prose lists — `routes_rooms.py:87-111`
- §3.4 notes — insert — ambiguity — `note_count` counts every note ever raised whatever its status; resolving/waiving never lowers it — `calc.py:639-644`
- §3.4 close — insert — ambiguity — legal in any phase other than `WRAPPED` — `routes_rooms.py:180`
- §3.4 cancel — insert — ambiguity — legal in any phase other than `WRAPPED`; `reason` not persisted; a `RETAKE_ISSUED` note and `retake_issued_count` untouched — `routes_rooms.py:209-222`
- §3.4 resolution — insert — ambiguity — legal in any phase other than `WRAPPED` — `routes_rooms.py:302`
- §3.5 reserve — insert — ambiguity — `seconds_per_frame` / `actual_seconds_per_frame` quantized to 2dp on ingest rather than rejected; `expected_render_pool_version` must be a JSON integer — `routes_render.py:69-70`, `helpers.py:143-169`
- §3.5 preemption — insert — ambiguity — a preempted job's `frames_completed` and `actual_seconds_per_frame` stay null and it keeps its reservation-time `cost_per_frame_cents`; victims in another shot/production reconcile the same way — `routes_render.py:121-128`
- §3.5 reserve — insert — ambiguity — a preempting critical admission advances the pool's `version` by exactly 1 for the request, not once per victim — `routes_render.py:130-131`, `store.py:94-107`
- §3.5 settle — insert — ambiguity — legal in any phase other than `WRAPPED` — `routes_render.py:177`
- §3.5 settle — insert — ambiguity — the outcome/`frames_completed` agreement check runs after the phase and job-state checks, so a non-`RESERVED` job reports `ERR_RENDER_JOB_STATE_INVALID` — `routes_render.py:178-184`
- §3.5 cancel — insert — ambiguity — no payload; legal in any phase other than `WRAPPED`; `frames_completed` set to 0 (vs null on preemption) — `routes_render.py:202-216`
- §3.5 cancel — insert — ambiguity — cancelled/preempted jobs carry no `final_cost_cents` or `actual_seconds_per_frame` but keep their quoted `cost_per_frame_cents` — `routes_render.py:214-216`
- §3.5 allowance — insert — ambiguity — admission is only *planned* before the allowance check, so a `CRITICAL` request refused by `ERR_RENDER_BUDGET_EXCEEDED` preempts nothing — `calc.py:459-484`, `routes_render.py:86-98`
- §3.7 earned-value read — insert — ambiguity — `variant` absent/empty → default; any other value is `ERR_VALIDATION` (validated, unlike §2.3 filters); the eight listed keys are the whole of `data` — `routes_shots.py:147-168`

Pass B found no place where pass A's edits contradicted its partition.

### Pass C — vendor + deliverables (11 ambiguity, 4 mismatch)
- §2.1 — insert — ambiguity — the vendor's two authorized read endpoints apply no ownership filter: a `PartnerRepresentative` may read/list every stage task and package, not only its own — `routes_vendor.py:166-185`
- §2.5 — revise — **mismatch** — was "Deliverable creation is the one operation legal in two phases"; deliverable submission and QC decision also require `PRODUCTION_ACTIVE` or `DELIVERY` — `routes_deliverables.py:56,128,165`
- §2.10 check 12 — revise — **mismatch** — was "the partner is not `SUSPENDED`"; issue and accept require `status` exactly `APPROVED` (an `ONBOARDING` partner is refused with `ERR_PARTNER_SUSPENDED`), only deliver merely forbids `SUSPENDED` — `routes_vendor.py:198,240,264`
- §3.5 — revise — **mismatch** — corrected pass B's claim that the settlement cross-field rule is *uniquely* evaluated after the phase/state checks; now cross-references the two sibling cases in pass C's partition — `routes_vendor.py:306-309`, `routes_deliverables.py:170`
- §3.6 ¶1 — insert — ambiguity — `legal_name` is any non-empty string, no length/character-class ceiling — `routes_vendor.py:33`
- §3.6 suspension — revise — **mismatch** — was "`NOT_STARTED` or `IN_PROGRESS`"; a scoped task already in `RETAKE` is likewise left in place and not retaken, and the link-clearing alone advances its `version` — `routes_vendor.py:83-86`
- §3.6 draft — insert — ambiguity — `package_code` is any non-empty string with no format enforced — `routes_vendor.py:130`
- §3.6 draft — insert — ambiguity — drafting is legal in any phase other than `WRAPPED`, and the partner's `status` is not examined at draft time — `routes_vendor.py:140`
- §3.6 issue — insert — ambiguity — linking overwrites any package link a task already carried; two packages may name the same stage task — `routes_vendor.py:221-223`
- §3.6 accept — insert — ambiguity — acceptance is legal in any phase other than `WRAPPED` (reachable, since the show may have advanced to `DELIVERY` after issue) — `routes_vendor.py:235`
- §3.6 deliver — insert — ambiguity — `watermark_applied` is mandatory and must be a JSON boolean, and the asserted value is stored either way; delivery is legal in any phase other than `WRAPPED` — `routes_vendor.py:254,259,274`
- §3.6 deliver — insert — ambiguity — both forms refresh each moved task's `submitted_at`, but only a **first** delivery writes `submitted_by_user_id`; a redelivery leaves the prior submitter in place (which is what the next stage review's SoD check compares) — `routes_vendor.py:283-287`
- §3.6 QC — insert — ambiguity — vendor QC is legal in any phase other than `WRAPPED` — `routes_vendor.py:301`
- §3.6 QC — insert — ambiguity — the score/decision agreement is evaluated after the phase and package-state checks, so a non-`DELIVERED` package reports `ERR_PACKAGE_STATE_INVALID` — `routes_vendor.py:301-309`
- §3.6 QC — insert — ambiguity — the `PASS` cascade stamps each approved task's `approved_at` and records the deciding supervisor in `reviewed_by_user_id` — `routes_vendor.py:322`, `flows.py:105-109`
- §3.8 create — insert — ambiguity — the `x` in `resolution` is lowercase only (`3840X2160` is `ERR_VALIDATION`); `expected_production_version` must arrive as a JSON integer — `routes_deliverables.py:19,41`
- §3.8 QC — revise — ambiguity — `FAIL` requires a non-blank `qc_note` (whitespace-only refused like an absent one), and that requirement runs after the phase and deliverable-state checks — `routes_deliverables.py:170`

**Pass C's four consciously-unpinned items**, all unobservable through the API (no request sequence distinguishes impl's choice from the alternative): the security-certification check firing only on `ONBOARDING → APPROVED` and never on reinstatement (a `SUSPENDED` partner can never hold `NONE`); `package_tasks` walking `stage_task_ids` in declared array order rather than `created_at`; `whole_days` flooring negative ages toward −∞ (a negative age takes the full 1.00 decay either way); a `qc_note` surviving a `PASS` with no note supplied (a row can only be QC-decided once).

**§2.8 consistency check across partitions:** pass B pinned `seconds_per_frame` / `actual_seconds_per_frame` locally in §3.5 rather than widening §2.8's field list. Pass C verified that `quality_min_score` and both partner quality scores are already in §2.8's list and already match `helpers.get_number(places=2)` / round-half-up-to-2 in `calc.partner_quality_score`, so no §2.8 widening was needed and pass B's local pin was left as-is. No cross-partition contradiction.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — 114 diff lines (57 changed line-pairs) — so the scan genuinely ran in all three passes.
- 469 lines, 27 headings, ends at `| ERR_BUDGET_WOULD_EXCEED | 402 |`. No sections added or dropped.
- `find` over `implementation/`, `test_suite/`, `test_helpers/` returns no `.py` file newer than `results.1.json`, confirming Steps 8 and 9 touched documentation only — the verified 8/8 green sweep (80/80 per round) still describes the code as it stands.

Pipeline complete through Step 9.

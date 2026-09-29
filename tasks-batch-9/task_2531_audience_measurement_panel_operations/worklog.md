# Worklog — task_2531_audience_measurement_panel_operations

## Step 1: Create task directory — 2026-09-03T06:30:23.922Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2531_audience_measurement_panel_operations` and `workspace/` (pre-assigned path from orchestration args; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T09:11:17.386Z

All three scaffold artifacts are complete and the lint is clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2531_audience_measurement_panel_operations/`)

| File | Lines | Bytes | Top-level key |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3480 | 194045 | `scenario … roles` (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2422 | 171965 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5379 | 388285 | `scaffold_corner_design` only |

Each file's tail ends on a real structural boundary (`SCAFFOLD.yaml` on the last `shared_operations` entry of §1.7; the difficulty file on the last `assert` string of `weight_cap_redistribution_conserves_total_weight_mass`; the corner file on the closing `rationale:` of the final `excluded_because` stub). All three parse with `yaml.safe_load`.

## §1.0–§1.7 inventory
14 entities · 10 state machines / 48 transitions · 3 concurrency rules · 12 calculations · 73 validations (priorities 1–73) · 72 endpoints · 84 errors · 7 roles. `complexity_layers`: dual_variant_calculation, cascading_side_effects, version_pinning_on_approval, optimistic_concurrency, rate_threshold_triggers; entity_topology flat, state_machine_shape cyclic, role_model segregation_of_duties, consistency_model immediate.

## §1.8 — 9 rules / 21 instances
dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 3.

## §1.9 — 9 sections / 91 instances (81 with test recipes, 10 `excluded_because` stubs)
entities 14 · state_machines 28 · calculations 17 · validations 8 · endpoints 7 · errors 4 · rbac 5 · cross_cutting_complexity_layers 6 · consistency_model 2.

Work completed in this final stretch: the `rbac` section (unauthenticated/unknown-role headers, peer-role denial of eight exclusive writes proving the role gate precedes existence checks, the confidential-read subset, row-level ClientUser cross-client denial on both endpoints named by priority 3, and segregation of duties at publish/finalize including rule 44 outranking rule 63), the `cross_cutting_complexity_layers` section (one entry per declared layer: two dual-variant stubs, the four-level universe-supersession cascade with its walk-back through repin/release, approval-time version pinning where a PUBLISHED run legally keeps a now-SUPERSEDED pin that a new run is refused, all three `concurrency_rules` in one interleaved sequence, and the 0.8000 fill boundary that releases and later re-arms the incentive boost), and the `consistency_model` section.

Verification results:
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1393 calls scanned).
- All 84 catalog error ids appear in §1.8 ∪ §1.9 (0 missing).
- 112 instance names across both design files, no duplicates; every stub's `difficulty_instance` resolves to a real §1.8 instance and no stub carries a `test_recipe`.
- Two lint violations found and fixed on the way: a literal `expected_market_version: 2` in `run_pinning_rules_fire_in_declared_priority_order` (now the captured pre-bump `${m73_v2}`, with the assertion reworded) and a `POST /tuning-intervals` issued `as: FieldTechnician` (that endpoint is MethodologyStatistician-only). A `GET /meters {market_id}` filter that §1.5 does not declare was also replaced with `GET /households {market_id}` → `GET /meters {household_id}`.

No sibling task directory was read at any point; every literal in §1.9 was re-derived from this task's own §1.2/§1.4/§1.5 text.

## Step 3: Copy shared files — 2026-09-03T09:11:33.976Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T09:31:10.770Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — **698 lines, 16,503 words**, written incrementally (one `Write` for chunk 1, then `cat >> … <<'PRDEOF'` appends; the §4/§5 tables were generated from the scaffold to eliminate transcription error). No single write approached the 64k cap.

**Section headings**
- `# Audience Measurement Panel Operations API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` → 2.1 RBAC · 2.2 API Response Structure (byte-verbatim, incl. both `####` subheads) · 2.3 Pagination, Ordering and Collection Filters · 2.4 The Logical Clock · 2.5 Common Record Properties · 2.6 Reference Resolution and the Validation Ladder · 2.7 Optimistic Concurrency on Pinned Parents · 2.8 Numeric Precision and Rounding · 2.9 Cascade Discipline and Conserved Quantities · 2.10 Segregation of Duties · 2.11 Accreditation Gates and Disclosure Persistence
- `## 3. Business Logic & Workflows` → 3.1 Markets, Quota Cells and the Recruitment Posture Gate · 3.2 Household Recruitment and the Enumeration Verdict · 3.3 Meter Deployment, Health Monitoring and the Fault Cascade · 3.4 Cooperation Incentives · 3.5 Population Universes and Editing Rule Sets · 3.6 Tuning Interval Ingest and the Editing Pass · 3.7 Weighting, Projection, Publication and Re-pinning · 3.8 Client Subscriptions and the Deliverable Lifecycle · 3.9 Methodology Change Governance and Accreditation Audits (9 subsections)
- `## 4. Endpoint Definitions` · `## 5. Error Code Catalogue`

**Coverage (documented / scaffold total), machine-verified**
- Entity field names: **149/149** in backticks (14 entities incl. the 4 common fields)
- Endpoint inputs + path params + query params: **90/90**
- Enum values across all entity fields: **all present**, 0 missing
- Errors: **84/84** in §5 table *and* **84/84** also named in §1–§3 prose (so no catalogue-only orphans); all 73 validation error ids appear in prose with their per-endpoint ordering
- Endpoints: **72/72** rows in the §4 table (Method · Path · Description · Authorized Role(s); "Any" for the 7-role reads, explicit 3-role list for the confidential tuning-interval and household-weight reads)
- State machines: **10/10** (Household; Meter `install_status`; Meter `health_status`; ProcessingRun; ClientDeliverable; MethodologyChange; ClientNotification; AccreditationAudit; UniverseEstimate; EditRuleSet) — every transition, precondition and side effect
- Calculations: **12/12**, including both variants of `household_compliance_rate` (ROLLING_30 / RUN_SCOPED) and `household_base_weight` (DESIGN / FINAL)
- Roles: **7/7**; concurrency rules **3/3**

**Hard Contracts:** Contract 1 PASS (0 missing identifiers). Contract 2 PASS (validation priority orderings written per-endpoint; OCC rules, `applies_to` scopes, numbered cascade links 1–5 / 1–4, conserved-quantity inverses, sibling-branch symmetry for the three audit outcomes and the two deliverable branches). Contract 3 PASS (0 backtick tokens in §3 start with `/` or begin with an HTTP method).

**Tail intact:** the file ends at the final `| ERR_DISCLOSURE_REQUIRED | 422 |` row of §5 — a complete row at a real section boundary, no audit footer.

Two notes worth relaying: (1) I corrected several formula constants mid-draft after re-reading the scaffold — the methodology credit factors are 1.0/1.0/0.5 (not discounted per-source as I first wrote), outlier households have their ascribed rows *deleted* rather than invalidated, and the compliance bar is 30 credited minutes per UTC date; also fixed an early `ERR_MARKET_VERSION_CONFLICT` mis-citation to `ERR_STALE_MARKET_VERSION`. (2) Four scaffold internal inconsistencies were resolved in favour of the endpoint descriptions (universe publish repins runs in `OPEN`/`EDITED`/`WEIGHTED`; direct rule-set publish also supersedes the prior published set; the notify fan-out covers suspended clients too; activation requires acknowledgements **and** the elapsed lead time, per the endpoint text plus validations 58 and 59, rather than the state machine's `OR`). The two design YAMLs were never opened.

**Orchestrator truncation check:** `wc -l` = 698; tail ends on a complete §5 table row (`ERR_DISCLOSURE_REQUIRED | 422 |`) at a real section boundary — not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T10:14:00.000Z

Implementation complete and verified.

## Files created — `workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 8 |
| `requirements.txt` (`Flask==3.0.3`) | 1 |
| `app.py` (blueprint registration, ApiError/HTTPException/catch-all handlers, `0.0.0.0:$PORT`) | 66 |
| `util.py` (Decimal/ROUND_HALF_UP helpers, ISO parse/format, request-id, shape validators) | 244 |
| `errors.py` (all 84 error ids → HTTP codes, `ApiError`) | 110 |
| `store.py` (14 in-memory dict collections, uuid/clock/version, dirty-set flush) | 164 |
| `response.py` (envelope, pagination, per-entity ordering, filters) | 137 |
| `auth.py` (`X-User-ID`/`X-User-Role`, 7 roles, confidential-read set) | 78 |
| `calculations.py` (12 calculations + domain constant tables) | 203 |
| `services.py` (roll-ups, posture, cascades, compliance, edit pass, weight pass) | 502 |
| `common.py` (body-ref resolution, OCC helper) | 61 |
| `routes_core.py` 158 · `routes_reference.py` 223 · `routes_household.py` 208 · `routes_meter.py` 150 · `routes_run.py` 383 · `routes_client.py` 363 · `routes_governance.py` 372 | 1857 |
| **total** | **3431** |

## Verification

- **Endpoints: 72 / 72.** Programmatically diffed Flask's `url_map` against the PRD §4 endpoint table: `declared but missing: []`, `extra not declared: []`.
- **Validations: 73 / 73.** Every `error_id` in the scaffold's 73 `validations[]` entries is raised in code; the only unmatched token is the generic placeholder `"ERR_<ENTITY>_NOT_FOUND"`, implemented as the per-collection `NOT_FOUND` map used by `common.must()` for ladder steps 4/5. All **84** catalogue error ids appear in code (none unreachable).
- **`python -m py_compile` passes on all 16 `.py` files**; every file ends at a real structural boundary.
- **Boot check:** fresh `PORT=18540 bash start.sh` served `POST /markets` → 201 with the full envelope, `GET /households` → 200 empty list (proving no seeding), and a header-less call → 401 `ERR_UNAUTHENTICATED`; then killed cleanly.
- **End-to-end smoke run: 0 failures** across ~60 calls exercising clock → market → cells → households → meters → install → enumeration → intervals → universe/rule-set publish → run open/detect-faults/edit/weight(FINAL)/re-weight(DESIGN)/publish → client → scheduled dispatch billing (gross 140000, discount 14000, 3 days late, penalty 6300, total 119700) → custom analysis start/deliver/revision/hold/release → methodology change draft/impact (0.76 MATERIAL, 720h)/notify/acknowledge/activate → audit open (posture FROZEN) / finalize QUALIFIED (posture released, disclosures appended) → incentive accrue/reverse → retire, plus 401/403/404 negative checks.

Storage is in-memory only (module-level dicts keyed by UUID); no SQLite, no JSON on disk, no `/tmp` cache, and no seeding or hardcoded entities at startup. Isolation constraint honored: only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md` and the skill were read — no `test_suite/`, `test_helpers/`, design YAMLs, or sibling tasks.

One notable fix during self-verification: `Store.now_iso` was a `@property` while three route modules called it, so business timestamps (`posture_changed_at`, `installed_at`, `published_at`, `superseded_at`, `last_enumeration_at`, `recruited_at`) were being assigned a bound method / raising `'str' object is not callable`. It is now a plain method, called consistently everywhere.

## Step 5: Generate unit tests — 2026-09-03T10:52:00.000Z

Stage 2 is complete. The suite is generated, compiles, and collects 348 tests with zero import or fixture errors.

## Files

`test_helpers/` (Stage 1, all pre-existing; 5 defects fixed this session — see below)

| file | lines |
|---|---|
| `test_helpers/__init__.py` | 24 |
| `test_helpers/api_client.py` | 1149 |
| `test_helpers/api_errors.py` | 213 |
| `test_helpers/assertions.py` | 548 |
| `test_helpers/constants.py` | 168 |
| `test_helpers/factories.py` | 354 |
| `test_helpers/fixtures.py` | 835 |
| `test_helpers/test_users.py` | 121 |
| `test_helpers/types.py` | 503 |

`test_suite/` (all new except `conftest.py`)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 30 | – |
| `test_01_dual_variant_calculations.py` | 334 | 5 |
| `test_02_combinatorial_formula.py` | 338 | 6 |
| `test_03_non_linear_lifecycles.py` | 372 | 6 |
| `test_04_transitive_cascades.py` | 327 | 5 |
| `test_05_validation_precedence.py` | 455 | 9 |
| `test_06_boundaries.py` | 661 | 12 |
| `test_07_cross_entity_gates.py` | 574 | 11 |
| `test_08_temporal_overlap.py` | 539 | 12 |
| `test_09_compensating_invariants.py` | 930 | 18 |
| `test_10_entities.py` | 1299 | 28 |
| `test_11_state_machines.py` | 2550 | 62 |
| `test_12_calculations.py` | 1719 | 30 |
| `test_13_validations.py` | 1741 | 50 |
| `test_14_endpoints.py` | 1679 | 50 |
| `test_15_errors.py` | 488 | 13 |
| `test_16_rbac.py` | 483 | 15 |
| `test_17_cross_cutting.py` | 774 | 12 |
| `test_18_consistency_model.py` | 205 | 4 |

## Coverage

- **Queue A (Difficulty): 84 tests** across all **21** non-stub §1.8 instances; every instance has ≥2 tests (min 2, max 7).
- **Queue B (Corner): 264 tests** across all **81** non-stub §1.9 instances; ≥1 each. The 10 `excluded_because` stubs were not translated.
- **Total 348 tests. Zero instances skipped** — every non-stub instance in both indices has verbatim PRD coverage and uniquely derivable outcomes.

Machine-verified with an AST pass: 348 docstrings, each with **exactly one** `Design:` line as its final line, each tag a verbatim `name:` from the source yaml (0 unknown tags, 0 dual-tagged, 0 untagged), and each docstring carrying at least one `PRD n.n: "…"` verbatim citation.

## Assertions dropped (partial, not whole instances)

No instance was skipped, but 8 individual sub-assertions were dropped as PRD-silent or non-uniquely-derivable rather than weakened: "opening a run bumps `Market.version`" (twice, §1.8 `run_window_identical_…` and §1.9 OCC layer); "a superseded run's counters are reset"; run window ending exactly at `effective_to` (PRD 3.6 check 6 is self-contradictory there); ingest "reversed window → `ERR_INVALID_WINDOW`" (the shape rule pre-empts it); "both body references missing → `ERR_CLIENT_NOT_FOUND`" (PRD 2.6 step 5 orders `processing_run_id` first); positional `data[0].id` claims on rows sharing one `created_at` with no PRD tie-break; and a `projected_average_audience` literal imported from a foreign recipe.

## Design-index defects corrected in favour of the PRD

Enum fixes per plan (`PANEL_REFERRAL`→`ONLINE_PANEL_TRANSFER`, `TUNER_DEAD`→`NO_SIGNAL`, missing mandatory `household_id` on every ingest). Substantive corrections: `impact_delta_pct` is 0.0000 not null on a DRAFT change; `notification_deadline_at` is stamped at notify, not at impact assessment; `request-revision` clears `delivered_at` and zeroes all four money fields; recipes that ship a second meter after the tuner's install-confirmation were reordered (PRD 3.3 ship check 1); a market listing's tie-break is `market_code` ascending, so DMA-603 precedes DMA-604; `reserved_incentive_cents` is not a QuotaCell field; several clock/window/wall-length violations in setups were repaired.

## Stage 1 defects fixed (test_helpers)

1. `fixtures.create_quota_cell` passed `market_id` positionally into `quota_cell_payload`, so it landed as `age_band` and the path id was lost.
2. `fixtures.accrue` validated 201; `POST /households/{id}/accrue-incentive` returns 200.
3. Four list helpers did `validate_success(...)["items"]`; PRD 2.2 makes a list `data` a plain array.
4. `assertions.expected_hold_credit_cents` / `expected_notification_lead_hours` raised `NameError` (`HOLD_CREDIT_PCT`, `NOTIFICATION_LEAD_HOURS` never imported).
5. `fixtures.active_household(extra_meter_types=…)` installed the tuner before shipping the extras, which PRD 3.3 refuses; it now ships all devices, then confirms all.

Also cross-checked helpers against the contract: all 72 SCAFFOLD endpoints are present on `ApiClient` (six docstring status codes corrected to 200), and `HTTP_STATUS_CODES` matches the PRD's 84-row error table exactly.

## Verification run

`python -m py_compile` passes on all 28 `.py` files (9 helpers + 19 suite files). Every file's last line is a complete statement inside a complete function. `python -m pytest test_suite --collect-only -q` → **348 tests collected in 1.62s**, no errors. `__pycache__` directories removed afterwards.

## Step 7: Iterate tests + fixes — 2026-09-03

Two 8-round parallel stability sweeps (`setsid nohup`, `--isolation per-test-server`, 348 tests/round).

- **Iteration 1:** 329/348 in all 8 rounds — 19 failures, identical set every round (fully deterministic, no flakiness). No `Terminated` in the sweep log, so no reaping.
- **Iteration 2 (after the fixes below):** **348/348 passed in all 8 rounds**, 0 failed / 0 errors / 0 skipped, union of non-passed tests across rounds = 0. ~617s per round.

### Implementation fixes (`workspace/implementation/`)
1. `routes_run.py` `open_run()` — added `"published_at": None` to the run insert. PRD 3.6 lists `published_at` among the opened-run fields that "all start null"; the key was only created at publication, so reads of an OPEN run raised `KeyError`.
2. `routes_run.py` run listing — added the `weight_variant` filter. PRD 2.3 names it verbatim (latent gap; no test exercised it).
3. `routes_client.py` deliverable listing — added the `hold_reason` filter. PRD 2.3 names it verbatim.
4. `routes_governance.py` audit listing — added the `outcome` filter. PRD 2.3 names it verbatim.
5. `routes_governance.py` notification listing — added the `impact_tier` filter. PRD 2.3 names it verbatim (latent gap).

### Test-suite fixes (`test_suite/`) — all made the test *more* faithful to PRD
6. Timestamp literals missing the three fractional digits PRD 2.5 mandates (`…T00:00:00Z` → `…T00:00:00.000Z`): `test_06_boundaries.py` (`due_at` ×2, `posture_changed_at`), `test_07_cross_entity_gates.py` (`notification_deadline_at` ×2, `acknowledged_at`, `activated_at`), `test_09_compensating_invariants.py` (`recruited_at` ×2, one of them in the shared `_dma_519_active_home` helper — the single edit unblocked 6 tests).
7. `test_11_state_machines.py` — `assert "2026-08" in retired["accrual_periods"]` replaced with a check that an entry exists whose `period_label == "2026-08"` and `reversed is False`. PRD 3.4 makes `accrual_periods` a list of objects, not of labels.
8. `test_15_errors.py` — `recruited["state"]` → `recruited["status"]`; PRD 3.2 names the household field `status`.

### Assertion deleted (1)
9. `test_14_endpoints.py` `test_identical_window_rerun_supersedes_the_open_run` — dropped `superseded_at` on a superseded **ProcessingRun** (STEP 1c partial coverage / PRD silence). PRD 3.6 names only `superseded_by_run_id` for run supersession and pointedly omits `superseded_at` from the run's null-start list (which does include `published_at`); §2.5 lists `superseded_at` generically and §3.5 attaches it to `UniverseEstimate`. The `state == "SUPERSEDED"` and `superseded_by_run_id` assertions were kept.

No test was deleted in whole, no assertion was weakened to an HTTP-status check, no `skip`/`xfail` was added, no PRD-required implementation check was removed, and storage remains in-memory only with no seeding.

## Step 7: Run tests and iterate (orchestrator record of subagent's returned summary) — 2026-09-03T11:33:00.000Z

All 8 rounds green. Final sweep: `348 passed / 0 failed / 0 errors / 0 skipped` in every round, union of non-passed tests across all 8 rounds = 0.

**Iterations run: 2** (each an 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`, 348 tests/round, ~617s/round).
- Iteration 1: 329/348 in all 8 rounds — 19 failures, byte-identical failure set in every round (fully deterministic; no `Terminated` in the sweep log, so no reaping artifact and no load-induced flake to re-confirm).
- Iteration 2: 348/348 in all 8 rounds.

**Tests deleted: 0 whole tests. 1 assertion removed for PRD silence.**
- `test_suite/test_14_endpoints.py` → `test_identical_window_rerun_supersedes_the_open_run`: dropped `assert _instant(retired["superseded_at"]) == _instant(CLOCK_T1)`. STEP 1c partial coverage / PRD silence — PRD 3.6 names only `superseded_by_run_id` for run supersession and pointedly omits `superseded_at` from the opened-run null-start list (which *does* include `published_at`); §2.5 lists `superseded_at` only generically and §3.5 attaches it to `UniverseEstimate`. The `state == "SUPERSEDED"` and `superseded_by_run_id` assertions were kept.

**Fixes applied to `test_helpers/`: none.** All test-side defects lived in `test_suite/`.

**Fixes applied to `test_suite/`:**
- `test_06_boundaries.py` — `due_at` ×2 and `posture_changed_at` literals given the three fractional digits PRD 2.5 mandates.
- `test_07_cross_entity_gates.py` — `notification_deadline_at` ×2, `acknowledged_at`, `activated_at`: same three-digit fix.
- `test_09_compensating_invariants.py` — `recruited_at` ×2, one inside the shared `_dma_519_active_home` helper; that single edit unblocked 6 tests.
- `test_11_state_machines.py` — `assert "2026-08" in retired["accrual_periods"]` → an entry with `period_label == "2026-08"` and `reversed is False`; PRD 3.4 makes `accrual_periods` a list of objects, not labels.
- `test_15_errors.py` — `recruited["state"]` → `recruited["status"]`; PRD 3.2 names the household field `status`.

**Fixes applied to `implementation/`** (all traced to verbatim PRD sentences):
- `routes_run.py` / `open_run()` — added `"published_at": None`; PRD 3.6 lists `published_at` among opened-run fields that "all start null", but the key only came into existence at publication, so reads of an OPEN run raised `KeyError`.
- `routes_run.py` / run listing — added the `weight_variant` filter (PRD 2.3 names it verbatim; latent gap, no test exercised it).
- `routes_client.py` / deliverable listing — added the `hold_reason` filter (PRD 2.3).
- `routes_governance.py` / audit listing — added the `outcome` filter (PRD 2.3).
- `routes_governance.py` / notification listing — added the `impact_tier` filter (PRD 2.3; latent gap).

No assertion was downgraded to an HTTP-status check, no `skip`/`xfail` was added, no PRD-required implementation check was removed to accommodate a fixture, no endpoint/field/side-effect was added without PRD traceability, and storage remains in-memory-only with no startup seeding.

**Orchestrator independent verification:** all 8 `workspace/implementation/results.{1..8}.json` exist (each ~109 KB, written 11:30) and each reports `passed=348 failed=0 total=348 errors=0 skipped=0`. Green claim confirmed against artifacts, not just the subagent's report.

## Step 8: Finalize PRD — 2026-09-03T11:40:00.000Z

PRD_FINALIZED.md written with two surgical edits.

## Line counts
- PRD.md: 698 lines; PRD_FINALIZED.md: 698 lines; 0% line delta (2 lines revised in place, +2 clauses / ~55 words).

## Changes
- **§3.6 (Opening a processing run — supersession)** — revise — after `superseded_by_run_id` is set, added that this pointer is the whole record of the event on the run and that a processing run carries **no `superseded_at` field of its own** — `implementation/routes_run.py:190-194` (only place a run reaches `SUPERSEDED`; no `superseded_at` key is ever written into a `processing_runs` row).
- **§4 preamble (Endpoint Definitions)** — insert — one sentence stating that the filter names in the Description column are illustrative and every collection endpoint additionally accepts each optional equality filter §2.3 lists for its collection — `implementation/routes_run.py:359-366`, `routes_client.py:357-364`, `routes_governance.py:282-288`, `routes_governance.py:368-374`.

## Per-edit pre-edit search log

**Edit 1 — subject: `superseded_at` and run supersession.**
(b) Enumerated/read: `grep -rn "superseded_at" implementation/*.py` → only `routes_reference.py:92` (UniverseEstimate draft init) and `routes_reference.py:126` (universe publication stamps the retired vintage); `grep -rn 'SUPERSEDED"' *.py` → every site that sets a `SUPERSEDED` state: `routes_run.py:191` (run, identical-window supersession — sets only `state` + `superseded_by_run_id`, then `release_run_artifacts` + `touch`), `routes_reference.py:125` (universe, stamps `superseded_at`), `routes_reference.py:200` (edit rule set direct publication — sets status only, **no** `superseded_at`), `routes_governance.py:209` (rule set superseded by change activation — status only). Also read `store.py` `insert`/`public` to confirm rows carry only explicitly written keys, so a `processing_runs` row's response body has no `superseded_at` at all; read `routes_run.py:166-196` open-run init dict (no such key) and `routes_run.py:306-347` repin (never sets it). Also `test_suite/test_10_entities.py:884,900` confirms `superseded_at` is asserted only for UniverseEstimate.
(c) Wording adjustment: dropped a first draft that said the stamp "belongs to universe vintages (§3.5)" — that would have implicitly claimed something about the two rule-set supersession paths (which also write no `superseded_at`, but PRD §3.5/§3.9 never promise one, so any statement there would be a new, unrequired universal). Final wording is scoped to the processing run only and says nothing about other entities, leaving §2.5's generic mention and §3.5's universe stamp untouched.

**Edit 2 — subject: optional equality filters on collection endpoints.**
(b) Enumerated/read: every `apply_filters` callsite in the implementation — `routes_core.py:77` (markets: recruitment_posture, accreditation_status), `routes_core.py:153` (quota cells: market_id, quota_status, incentive_boost_active), `routes_reference.py:147` (universe estimates: market_id, status), `routes_reference.py:220` (rule sets: status), `routes_household.py:202` (market_id, quota_cell_id, status, enumeration_verdict), `routes_meter.py:144` (household_id, install_status, health_status, meter_type), `routes_run.py:98` (intervals: meter_id, household_id, processing_run_id, state, source_methodology, ascribed), `routes_run.py:359` (runs: +weight_variant), `routes_run.py:379` (weights: processing_run_id, household_id, weight_variant, capped), `routes_client.py:144` (clients: tier, status), `routes_client.py:357` (deliverables: +hold_reason), `routes_governance.py:241` (methodology changes: state, target_edit_rule_set_id, proposed_edit_rule_set_id, supersedes_change_id), `routes_governance.py:282` (notifications: +impact_tier), `routes_governance.py:368` (audits: +outcome); plus `response.py::apply_filters` (unknown params ignored, bool/int coercion). Result: impl supports **exactly** the §2.3 list for all 13 collections named there, and for methodology changes — which §2.3 omits entirely — exactly the set the §4 row names.
(c) Wording adjustment: phrased as "**additionally** accepts each optional equality filter §2.3 lists for its collection" rather than "§2.3's list is the complete set", so the methodology-changes filters (named only in the §4 row, absent from §2.3) are not excluded; and the sentence adds nothing for collections whose §4 row already omits any filter mention (e.g. `GET /markets`). No table row was narrowed or rewritten, so the other systematically-abbreviated rows (quota cells, households, meters, tuning intervals, household weights) are now covered by the same clause instead of being implicitly restricted.

**Items deliberately left unpatched** (PRD already determines the behavior; pure fixture bugs or latent gaps closed by verbatim PRD sentences): three-fractional-digit literals for `due_at`/`posture_changed_at`/`notification_deadline_at`/`acknowledged_at`/`activated_at`/`recruited_at` (§2.5); `accrual_periods` as objects with `period_label`/`accrued_cents`/`reversed` (§3.4); household field named `status` (§3.2); `published_at` starting null on an opened run (§3.6, verbatim null-start list).

## Step 9: Complete PRD — 2026-09-03T12:02:55.415Z

Run as three sequential file-partitioned passes over `implementation/` (the whole-file scan is unreliable in one shot; partitioning also guarantees the scan actually ran rather than producing a byte-identical copy).

### Pass 1 — app.py, store.py, util.py, errors.py, response.py, auth.py, common.py, routes_core.py, routes_reference.py, routes_household.py, routes_meter.py

`PRD_FINALIZED.md` 698 lines / 120,314 chars → `PRD_COMPLETED.md` 704 lines / 128,307 chars (+6 lines, +7,946 chars). No sections added; two rows added to the §5 catalogue. Verified the §5 table matches `errors.ERROR_STATUS` exactly (84 ids, zero status mismatches) plus the two transport-layer ids `app.py` hardcodes. **32 changes — 28 ambiguity-pins, 4 mismatch-revisions.**

- §2 preamble — insert — ambiguity — store starts empty; nothing seeded/preloaded; clock default is the only pre-request state — `store.py:1-4`, `app.py:3-5`
- §2.1 — revise — ambiguity — `X-User-ID` whitespace-only counts as empty; role match is exact and case-sensitive — `auth.py:37-40`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `util.py:82-84`
- §2.2 — revise — **mismatch** — `api_request_timestamp` reads real wall-clock time, not the logical clock — `util.py:78-79`, `response.py:17`
- §2.3 — insert — ambiguity — non-integer/out-of-band `limit` and negative `offset` → `ERR_INVALID_REQUEST` 422 (not clamped); whitespace tolerated — `response.py:56-77`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence, under the default and all three overrides — `response.py:80-91`, `store.py:144-149`
- §2.3 — insert — ambiguity — string filters exact-match; boolean filters accept `true/false/1/0` any case else 422; undeclared params ignored; repeated param reads first; filters validated before pagination — `response.py:113-137`
- §2.4 — insert — ambiguity — startup clock renders `2026-08-01T00:00:00.000Z`; response carries only the two fields; HTTP 200 — `routes_core.py:19-30`, `store.py:13`
- §2.5 — insert — ambiguity — `updated_at` stamped once at request completion, identical across all rows the request moved — `store.py:102-111`
- §2.5 — revise — **mismatch** — `version` increments exactly 1 *per mutating request*, not per write; multi-link cascades still bump 1; failed requests bump nothing — `store.py:93-111`
- §2.6 step 5 — insert — ambiguity — nested `cell_populations.quota_cell_id` is not a body reference; unresolvable → `ERR_UNIVERSE_CELL_COVERAGE`, not 404 — `routes_reference.py:28-29,46-53`
- §2.6 step 6 — insert — ambiguity — body must be a JSON object; absent/empty body read as `{}`; non-object or unparseable → 422 never 400/415; JSON `null` = absent; undeclared inputs ignored — `util.py:105-124`, `app.py:47-49`
- §2.6 step 7 — insert — ambiguity — integer/number type strictness (booleans and numeric strings refused); ISO-8601 latitude (`T`/space, optional seconds/fraction, `Z`/offset/none) and canonical re-render — `util.py:11-75,163-213`
- §2.6 — insert — ambiguity — unmatched path → `ERR_NOT_FOUND` 404; undeclared method → `ERR_METHOD_NOT_ALLOWED` 405; trailing slash insignificant — `app.py:26,42-46`
- §2.8 — insert — ambiguity — declared scales govern precision not wire spelling; `fill_rate` 0.0000 renders `0.0` — `store.py:152-164`
- §3.1 — insert — ambiguity — `delta_cents` any integer; `memo` required 1–400; adjustment re-derives no roll-up or posture — `routes_core.py:89-100`
- §3.2 — insert — ambiguity — the two no-op status/verdict enumeration combinations — `routes_household.py:94-101`
- §3.2 — insert — ambiguity — `retired_reason` 1–400 — `routes_household.py:113`
- §3.3 — insert — ambiguity — shipped meter's `last_fault_code` starts null — `routes_meter.py:49`
- §3.3 — insert — ambiguity — install-confirmation reads no body at all — `routes_meter.py:58-72`
- §3.3 — insert — ambiguity — fault report's `INSTALLED` requirement is `ERR_METER_NOT_INSTALLED`, evaluated *after* the health check — `routes_meter.py:82-87`
- §3.3 — insert — ambiguity — `repair_note` 1–400, not stored — `routes_meter.py:102`
- §3.3 — insert — ambiguity — `removal_note` 1–400, not stored — `routes_meter.py:120`
- §3.4 — insert — ambiguity — `period_label` 1–40, opaque string — `routes_household.py:134`
- §3.4 — insert — ambiguity — reversal `memo` 1–400; reversal admitted at any status incl. `RETIRED` — `routes_household.py:173-182`
- §3.5 — revise — ambiguity — `cell_populations` array/entry shapes incl. `population_persons` ≥ 0, refused as a shape failure ahead of the concurrency check — `routes_reference.py:17-43`
- §3.5 — insert — ambiguity — empty `cell_populations` is valid for a cell-less market; totals 0 — `routes_reference.py:46-53,86-89`
- §3.5 — revise — **mismatch** — the 28-day bar is applied to *every* vintage currently `PUBLISHED`, not one "current" vintage; exactly 28 floored days suffices — `routes_reference.py:104-110`
- §3.5 — insert — ambiguity — a reference-object supersession leaves a `WEIGHTED` run's weight rows, `total_weight_mass` and projection intact — `routes_reference.py:129-134,203-207`
- §3.5 — insert — ambiguity — duplicate rule-set `label` → `ERR_INVALID_REQUEST` — `routes_reference.py:171-173`
- §3.5 — revise — **mismatch** — rule-set publish cascade hits `OPEN`/`EDITED`/`WEIGHTED` only (not "non-terminal"), leaves `PENDING_REPIN` runs alone, and records no supersession timestamp — `routes_reference.py:196-207`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` 404 and `ERR_METHOD_NOT_ALLOWED` 405 rows — `app.py:42-46`

Deliberately not pinned: the `ERR_INTERNAL` 500 handler (`app.py:53-56`) — it fires only on an implementation defect, so documenting it as contract would over-specify rather than disambiguate.

### Pass 2 — calculations.py, services.py, routes_run.py

704 lines before → 704 after (all in-paragraph); 128,307 → 132,440 chars (+4,133). **16 edits — 10 ambiguity-pins, 6 mismatch-revisions.**

- §3.6 Ingest — insert — ambiguity — `household_id` is the one *optional* input and the stored value is always copied from the meter, so omission is accepted — `routes_run.py:35`, `:73`
- §3.6 Ingest — insert — **mismatch** — the wall-length `tuning_minutes` bound is skipped entirely when `start_iso` is not strictly before `end_iso`, so the caller sees `ERR_INVALID_WINDOW`, not `ERR_INVALID_REQUEST` — `routes_run.py:45-51`
- §3.6 Open run check 6 — revise — **mismatch** — effectivity range is **closed** at both ends; PRD said "`effective_to` itself exclusive" while impl accepts `end_iso == effective_to` — `routes_run.py:142`
- §3.6 Open run — revise — ambiguity — the future-window bound reports `ERR_INVALID_WINDOW` and is evaluated **last**, after the overlap check; opening a run advances the parent market's `version` by one — `routes_run.py:161-163`, `:195`
- §3.7 Weighting preconditions — revise — **mismatch** — deleted the false "at least one quota cell must yield a non-zero denominator" requirement (impl has no such check); named the two real errors, their position after the three ordered checks, and that the pinned rule set's `status` is not re-examined — `routes_run.py:247-256`
- §3.7 Cell exclusion — revise — **mismatch** — a cell is excluded either for a zero denominator **or** because the pinned vintage carries no `cell_populations` entry for it (the only case that actually fires); `excluded_cell_count` counts only contributors' cells; an all-excluded run still succeeds with mass 0.0000 and projection 0 — `services.py:459-460`, `:492`
- §3.7 Redistribution step 4 — insert — ambiguity — a receiver mass of 0 yields share 0.0000 with no division attempted — `services.py:192-195`
- §3.7 Re-weighting — revise — **mismatch** — removed `intab_snapshot_count` from the overwritten-field list; no weighting pass ever rewrites it — `services.py:489-492`
- §3.7 Re-pinning — insert — ambiguity — both pin inputs are optional and a call supplying neither is accepted, returning the run to `OPEN` on existing pins — `routes_run.py:311-335`
- §3.7 Publication — revise — ambiguity — named `ERR_UNIVERSE_NOT_PUBLISHED` and pinned it as evaluated after all four ordered checks — `routes_run.py:278-281`
- §3.6 Editing pass — revise — ambiguity — named `ERR_RULE_SET_NOT_PUBLISHED` and pinned the run-state check as first — `routes_run.py:214-219`
- §3.3 Fault detection — revise — ambiguity — meters are visited in `created_at` ascending order — `services.py:199`
- §3.3 Fault detection — revise — ambiguity — an already-`FAULTED` meter re-scanned only re-records `missing_minutes_last_scan`: no `fault_count` bump, no `last_fault_code` overwrite, no second cascade — `services.py:213-219`
- §3.3 Fault detection — revise — ambiguity — "scanned household" pinned as one owning ≥1 scanned meter; a household with no `INSTALLED` meter keeps its stored rate — `services.py:224-229`
- §3.3 Fault detection — revise — ambiguity — the response body is the unchanged run row — `routes_run.py:207`
- §3.5 Supersession cascade — revise — **mismatch** — held deliverable states named explicitly as `SCHEDULED`/`REQUESTED`/`IN_PROGRESS`/`REVISION_REQUESTED` (PRD said "any non-terminal state", which would wrongly include `HELD`), plus `held_from_state`, run/deliverable `created_at` ordering, the per-hold `held_deliverable_count` and 5% SLA credit, and `weight_variant` added to the untouched list — `services.py:254-290`
- §3.9 Impact analysis — insert — ambiguity — the three sub-scores are carried at full precision; the 4-dp rounding of the weighted total is the calculation's only rounding — `calculations.py:144-155`

Pass 2 explicitly deferred §3.9 activation links 2–4 to pass 3: `routes_governance.py:218,226` passes its **own** state list and does its own weight-row deletion rather than reusing `services.repin_runs`.

### Pass 3 — routes_client.py, routes_governance.py

704 lines before → 704 after (all in-paragraph); 132,440 → 140,650 chars (+8,210). **22 edits — 19 ambiguity-pins, 3 mismatch-revisions.**

- §3.8 Clients — insert — ambiguity — `contract_market_ids` entries are never resolved against markets (unknown id accepted); 0/>10/duplicate → `ERR_INVALID_REQUEST` — `routes_client.py:36-38`
- §3.8 Clients — revise — **mismatch** — PRD described a tier-change refresh, but §4 declares no operation that rewrites `tier`; rewritten as counterfactual with derived fields fixed at registration — `routes_client.py:39-52`
- §3.8 Suspension — insert — ambiguity — `suspended_reason` min 1 char / no max; no state check so re-suspending a `SUSPENDED` client is accepted; sweep walked in deliverable `created_at` ASC; `held_deliverable_count` is a **recount** of all `HELD` rows, not an increment; no SLA credit — `routes_client.py:56-78`
- §3.8 Scheduled placement — insert — ambiguity — remaining initial fields (`discount_cents`, `late_penalty_cents`, `days_late` 0; `held_from_state`, `hold_reason`, `findings_summary`, `delivered_at` null) — `routes_client.py:113-131`
- §3.8 Scheduled placement — insert — ambiguity — placing writes no client/run field, so neither parent's `version` moves (contrast custom analysis) — `routes_client.py:113-132`
- §3.8 Custom analysis — insert — ambiguity — `requested_cell_count` max 24 — `routes_client.py:179`
- §3.8 Custom analysis — insert — ambiguity — of the two body refs the run resolves first → `ERR_PROCESSING_RUN_NOT_FOUND` wins — `routes_client.py:172-175`
- §3.8 Custom analysis — insert — ambiguity — full initial money/hold/narrative field set — `routes_client.py:192-210`
- §3.8 Branch A — insert — ambiguity — the three dispatch checks are normatively ordered (suspension before run state before row state) — `routes_client.py:236-245`
- §3.8 Branch B — insert — ambiguity — `findings_summary` min 1/no max, shape validated before the suspension then state check; delivery re-checks no `kind` — `routes_client.py:257-266`
- §3.8 Billing step 4 — insert — ambiguity — a null `due_at` prices with `days_late` 0, and that case is reachable (publication stamps only `SCHEDULED` rows) — `routes_client.py:153-158`, `routes_run.py:289-301`
- §3.8 Billing — revise — **mismatch** — "a tier change before delivery does affect the price" recast as counterfactual (fee read from the client row at delivery) — `routes_client.py:159-160`
- §3.8 Billing — insert — ambiguity — the client write is unconditional, so delivery advances the client's `version` even at 0 credit — `routes_client.py:162-164`
- §3.8 Revisions — insert — ambiguity — `reason` required, validated, not stored; ownership check precedes body validation — `routes_client.py:277-284`
- §3.8 Revisions — insert — ambiguity — `days_late` and `due_at` are **not** reset by a revision; the earlier credit is not clawed back — `routes_client.py:289-296`
- §3.8 Holds — insert — ambiguity — `REVISION_REQUESTED` is not manually holdable (unlike §3.5's cascade); hold checks neither client nor run — `routes_client.py:311-321`
- §3.8 Releases — insert — ambiguity — `held_deliverable_count` decrement clamped at 0; release checks nothing about the client — `routes_client.py:342-344`
- §3.9 Drafting — insert — ambiguity — `supersedes_change_id` state check precedes `ERR_RULE_SET_NOT_DISTINCT`; `affected_market_ids` unresolved; full null/zero initial field set — `routes_governance.py:41-66`
- §3.9 Impact analysis — insert — ambiguity — error ids and order for the target-`PUBLISHED`/proposed-`DRAFT` re-checks — `routes_governance.py:92-99`
- §3.9 Notification — insert — ambiguity — counters set from this fan-out alone, so surviving `ACKNOWLEDGED`/`CANCELLED` rows count toward neither and a client can hold one row per round — `routes_governance.py:126-139`
- §3.9 Revision — insert — ambiguity — `reason` not stored; the cleared fields go to **null**, `impact_delta_pct` included (not back to 0.0000) — `routes_governance.py:150-163`
- §3.9 Activation — insert — ambiguity — `ERR_RULE_SET_NOT_DRAFT` for the proposal; the target's `status` is not re-examined — `routes_governance.py:196-200`
- §3.9 Link 2 — insert — ambiguity — sweep keyed on the rule-set pin only (not `affected_market_ids`); `WEIGHTED`/`PENDING_REPIN`/`PUBLISHED`/`SUPERSEDED` untouched; `weight_variant`, counters and disclosures untouched — `routes_governance.py:212-223`
- §3.9 Link 3 — insert — ambiguity — the state list is exactly three (`REVISION_REQUESTED` excluded, unlike §3.5); already-`HELD`/`DELIVERED` untouched; link fires only if link 2 moved a run — `routes_governance.py:225-228`
- §3.9 Opening an audit — insert — ambiguity — the scoped rule set needs no relation to the market; posture and `publication_blocked` do not bar opening — `routes_governance.py:303-309`
- §3.9 Finalizing — insert — ambiguity — `limitation_disclosures` is a required array of non-empty strings even for `ACCREDITED` — `routes_governance.py:330-332`
- §4 table — revise — **mismatch** — `/start` said "SCHEDULED or REQUESTED"; now "REQUESTED or REVISION_REQUESTED CUSTOM_ANALYSIS of an ACTIVE client" — `routes_client.py:216-228`

### Totals and orchestrator verification

**70 edits total across the three passes — 57 ambiguity-pins, 13 mismatch-revisions.**

Pass-3 integrity check: `wc -l` = 704, `wc -c` = 140,650. Headings: `#` title (1), `## 1. Introduction` (3), `## 2. Global Specifications & System-Wide Principles` (11), `## 3. Business Logic & Workflows` (203), `## 4. Endpoint Definitions` (536), `## 5. Error Code Catalogue` (615). §5 table intact with header plus 86 error rows; set-diff against `implementation/errors.py` shows zero impl error ids missing, and the only two catalogue-only ids are `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED`, raised by `app.py`'s `HTTPException` handler.

Orchestrator's own check: `PRD.md` 698 lines / 120,015 chars → `PRD_FINALIZED.md` 698 / 120,314 → `PRD_COMPLETED.md` 704 / 140,650. `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (134 changed lines, +20,336 chars over it), so the scan genuinely ran. Tail ends on a complete §5 table row (`ERR_DISCLOSURE_REQUIRED | 422 |`) at a real section boundary. `implementation/` and `test_suite/` were not modified in Steps 8–9, so the Step 7 result stands: 8/8 rounds at 348/348.

## Pipeline complete — 2026-09-03T12:02:55.415Z

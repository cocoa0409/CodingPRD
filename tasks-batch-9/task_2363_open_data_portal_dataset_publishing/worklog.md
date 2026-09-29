# Worklog — task_2363_open_data_portal_dataset_publishing

## Step 1: Create task directory — 2026-09-02T04:15:56.262Z

Created `tasks/task_2363_open_data_portal_dataset_publishing/` and `tasks/task_2363_open_data_portal_dataset_publishing/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:52:41.460Z

All three scaffold artifacts are complete and lint-clean.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

`worklog.md` and `workspace/` were already in the directory (timestamped before generation); untouched.

### Scaffold counts (§1.0–§1.7)
- scenario stored verbatim (byte-identical to the supplied text), `domain_name: open-data-portal`, `api_prefix: /open-data`
- 12 entities, 9 state machines (Dataset carries two parallel dimensions: `publication_status` and `currency_status`), 2 OCC concurrency rules, 12 calculations, 34 ordered validations, 75 endpoints, 56 error ids, 5 roles
- complexity profile: `workflow_orchestration` + `compliance_audit`, topology `graph`, machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`

### Design instance counts
- §1.8: **22 instances** across the 9 required rule_ids (2–3 each) — dual-variant priority scoring, 84.99 vs 85.00 rounding order, non-linear privacy/remediation/run cycles, 3- and 4-hop cascades, three priority-conflict pairs, half-up and grace-boundary precision, cross-entity readiness gates, half-open window + cooldown and closed-interval capacity overlap, three credit/row-count conservation invariants.
- §1.9: **99 instances** (80 with full recipes, 19 `excluded_because` stubs) across all nine guide sections: entities 11, state_machines 13, calculations 16, validations 22, endpoints 6, errors 15, rbac 9, cross_cutting_complexity_layers 6, consistency_model 1.

### Verification performed
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1560 calls scanned across 102 instances)
- Independent checks: zero duplicate names across §1.8 ∪ §1.9; zero unbound `${var}` placeholders (setup → trigger → assert order); every stub's cited `difficulty_instance` exists; every grounds entry resolves to a declared §1.1–§1.6 element; all 56 error ids exercised somewhere in §1.8 ∪ §1.9; no stub carries a `test_recipe`.

Three source-of-truth issues found and fixed while authoring the corner file: (1) `PipelineRun.skip_reason` was self-contradictory across three places when dataset retirement cascades — now conditional on the cascade origin; (2) `ERR_DATASET_NOT_PUBLISHED` was ambiguous for `POST /dataset-versions`, which must accept `UNDER_REMEDIATION` since a corrective version is what lifts remediation; (3) `scenario:` used a literal block (`|`), which injected newlines — switched to `>-` so it folds to the exact verbatim string.

## Step 3: Copy shared files — 2026-09-02T05:52:41.460Z

Copied `INSTRUCTION.md` to `tasks/task_2363_open_data_portal_dataset_publishing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:08:10.719Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing/workspace/PRD.md`.

**Shape:** 494 lines. §1 Introduction; §2 Global Specifications with 11 subsections (RBAC, response envelope verbatim, pagination/filtering, identity & version counters, rounding discipline, OCC, the 34-priority validation ladder, left-to-right path resolution, posture gate, credit ledger, cascade/recompute discipline); §3 Business Logic with 9 domain-derived subsections (departmental inventory & prioritisation, licences & metadata record, privacy screening & clearance, readiness/publication/retirement, pipelines & runner windows, run settlement & version ledger, quality issues & corrections, requests/showcase/analytics, currency SLAs & the portal sweep); §4 endpoint table (75 rows, 4 columns); §5 error catalogue (56 rows). File ends at §5 with no audit footer.

**Coverage audit (all three Hard Contracts PASS, verified mechanically against SCAFFOLD.yaml):**
- **Contract 1 — Field-Name Coverage: PASS.** 159/159 `entities[].fields[].name`, 87/87 endpoint `input` identifiers (optional markers stripped), 13/13 path parameters all appear verbatim in backticks. Scaffold defines no `query_params`. All 56 error IDs and all 75 paths present.
- **Contract 2 — Rule Coverage: PASS.** All 34 validation priorities render in order with exactly the scaffold's error-ID sets and `applies_to` scopes (1:1 diff, no drift). All 47 state-machine transitions across the 9 machines render as explicit `FROM → TO` arrows with preconditions and side-effect cascades. Both `concurrency_rules[]` OCC rules covered in §2.6 (412 / `ERR_STALE_DATASET_VERSION`). All 12 calculations rendered in prose with constants, pinned rounding orders, and sibling-branch symmetry (e.g. `READY → RETIRED` vs `PUBLISHED → RETIRED`, `ACCEPT`/`RETURN`, `CLEAR`/`BLOCK`, all three decommission origins).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path.

**Two notes worth relaying:**
1. I tightened §2.3: an earlier draft enumerated per-collection filter sets for 11 collections, but the scaffold only specifies filters for two list endpoints (departments → `code`/`compliance_posture`; metadata-records → `dataset_id`/`license_id`/`status`) and declares no `query_params` anywhere. §2.3 now states exactly those two and says the remaining list endpoints accept `limit`/`offset` only. No field name was lost — every affected identifier is still backticked elsewhere.
2. Scaffold inconsistencies reconciled explicitly in the prose (each resolved toward the entity/calculation definitions, which are the more canonical source): showcase initial `status` (`SUBMITTED`, not the endpoint side-effect's `PENDING`); `armed_window_count` deltas (+1 on arm/resume, −1 on leaving `ARMED`, not decremented again on `SUSPENDED → DECOMMISSIONED`); phantom constant names in endpoint `side_effects` replaced by the canonical `FAILURE_STREAK_LIMIT: 3` / net-reject threshold 3 / `demand_signal` 0.00; `consecutive_failure_index` seeded from the pipeline's current streak at scheduling and overwritten with the post-increment value on failure. §4's role column uses each endpoint's own `roles` list where it differs from the state machine's `actor`.

## Step 5: Generate unit tests — 2026-09-02T07:47:31.657Z

Test generation for task_2363 is complete.

### Files written

**Stage 1 — `test_helpers/`**: `types.py`, `api_errors.py` (56 error ids + status map), `api_client.py` (`ApiClient` over prefix `/open-data`, all 75 endpoints), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

**Stage 2 — `test_suite/`**: `conftest.py` plus 16 test modules, **120 tests total, all collecting clean**.

| file | tests | source |
|---|---|---|
| test_01 priority scoring / engagement | 5 | queue A |
| test_02 metadata standard record | 6 | queue A |
| test_03 privacy reidentification review | 5 | queue A |
| test_04 pipeline arming and windows | 8 | queue A |
| test_05 run settlement and credits | 6 | queue A |
| test_06 run failure and currency aging | 6 | queue A |
| test_07 remediation cascade and version ledger | 8 | queue A |
| test_08 catalog entity records | 10 | Corner/entities |
| test_09 state machine journeys | 12 | Corner/state_machines |
| test_10 derived calculations | 9 | Corner/calculations |
| test_11 publication validation gates | 8 | Corner/validations |
| test_12 run and review validation gates | 7 | Corner/validations |
| test_13 endpoint behaviours | 6 | Corner/endpoints |
| test_14 typed error responses | 10 | Corner/errors |
| test_15 role authorization | 9 | Corner/rbac |
| test_16 concurrency and visibility | 5 | Corner/cross_cutting + consistency_model |

**Queue A: 44 tests** covering 21 of 22 difficulty instances, every one with ≥2 tests. **Queue B: 76 tests** covering 76 of 80 non-stub corner instances, one test each. The 19 `excluded_because` corner stubs got no tests; all 19 `difficulty_instance` cross-references resolve to real difficulty instances.

### Instances skipped (5, all PRD-first filter failures)

- `Difficulty/priority_pair_validation_conflict/publish_aggregation_safety_outranks_embargo_window`, `Corner/validations/publish_after_embargo_expiry_succeeds`, `Corner/validations/publish_during_active_embargo_returns_4XX` — the PRD mentions `embargo_until_utc` only as a *read* precondition (publish, run start); it is absent from the dataset-creation field list and there is no dataset update endpoint, so the premise cannot be established through documented endpoints.
- `Corner/entities/dataset_listing_filters_by_status_and_paginates` — the PRD grants named filters only to the department register and the metadata-record collection and then closes the door explicitly, so the instance's filtered `total_count` is not derivable.
- `Corner/errors/run_creation_on_a_draft_pipeline_returns_4XX` — `ERR_PIPELINE_NOT_ARMED` is PRD-stated for start and requeue but not for run creation; the only supporting text is an endpoint-table description cell, which the citation rules bar.

No instance was weakened, and no skip/xfail marker or placeholder was emitted. Several individual sub-assertions inside kept instances were dropped for the same reason (undocumented list filters, unstated null defaults, `created_at == updated_at`, showcase re-commit idempotency) and are noted in the docstrings' scope rather than asserted.

### Audit results (all clean)

- `python -m py_compile` and `pytest --collect-only` pass; 120 tests, no duplicate test names, pyflakes clean.
- Every test carries exactly one `Design:` line as the last line of its docstring; zero untagged, zero dual-tagged; every tag resolves to a real non-stub instance in the correct index.
- Citation pass: 411 quoted spans of ≥8 words checked against `workspace/PRD.md` — 405 contiguous verbatim, 6 elided with every retained part verbatim. One defect found and fixed in `test_07` (a mid-sentence elision was rewritten as a contiguous quote).
- Static binding check: every `api.*`, `fixtures.*` and `factories.*` call in all 16 files binds against the frozen helper signatures.
- No occurrence of the word "scaffold", no TODO/FIXME, no skip/xfail anywhere in `test_suite/`.

## Step 6: Generate implementation — 2026-09-02T07:47:31.657Z

The implementation is complete, boots cleanly from a fresh process via `start.sh`, and has been smoke-tested end to end.

### Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing/workspace/implementation/`:

- `start.sh` (executable) — `set -euo pipefail`, `cd "$(dirname "$0")"`, `PORT="${PORT:-10000}"`, import-guarded `pip install` (with `--break-system-packages` fallback), `exec python3 app.py`
- `app.py` — app factory, six blueprints under `/open-data`, `before_request` resets the per-request `g.touched` set, handlers for `ApiError` / 404 `ERR_NOT_FOUND` / 405 `ERR_METHOD_NOT_ALLOWED` / 500 `ERR_INTERNAL`, `/health`, `app.run(host="0.0.0.0", port=$PORT, threaded=False)`
- `core.py` — in-memory `Store` (12 dicts + `logical_now` pinned to `2026-08-01T00:00:00Z` + `_seq`), envelope builders, 57-entry `ERROR_STATUS` map, `caller()` role resolution, the whole validator family, pagination/sorting, `new_row`/`touch` (one `version` bump per row per request)
- `calc.py` — all pure math and constants (engagement, priority/tier, community pressure, reidentification risk, aggregation geography, metadata completeness, settlement waterfall, escrow, reputation, demand signal, compliance posture, cadence/grace/SLA tables) using `Decimal` + `ROUND_HALF_UP`
- `services.py` — cross-entity recomputes, cascades (staleness alerting, escrow release, pipeline suspend/decommission, version minting, settlement), and the 12 serialisers
- `common.py` — not-found map, `find`, `dept_scope`, `member_scope`, `bad_state`
- `routes/__init__.py`, `routes/registry.py` (15 endpoints), `routes/datasets.py` (13), `routes/artifacts.py` (13), `routes/pipelines.py` (18), `routes/community.py` (14), `routes/ops.py` (2)
- `requirements.txt` (`flask>=2.0`)

### Endpoint count
**75** method+path routes under `/open-data` (matching PRD §4's 75 rows; the scaffold header's "74" undercounts by one). Storage is in-memory dicts only — no SQLite, no disk JSON, no `/tmp`, no seeding at startup.

### Verified numerics
Metadata completeness `[30,20,15,15,10,10] → 100.00` and the trap case `→ 84.99`; settlement `95000 rows → compute 40.00, subtotal 40.00, 10% discount → total 36.00` keyed on the pre-discount subtotal, drawn escrow-first; four-bucket conservation (`credit_ledger_balanced: true` across grant → arm → three failures → resume → decommission); engagement `1 epoch (1000 api, 500 dl) → 8.00` (weights not renormalised); AS_OBSERVED priority `37.90`; runner window conflict at boundary (`130` conflicts against `[60,120)+30` cooldown, `150` does not); failure streak at 3 → `SUSPENDED/FAILURE_STREAK` + dataset floored to `STALE` + department `RESTRICTED`, all reversed on resume/decommission; per-request single `version` increment.

### PRD ambiguities resolved
1. Showcase entries start at `SUBMITTED`; `decide` accepts both `APPROVE`/`APPROVED` and `REJECT`/`REJECTED`; submit returns 201 with the Dataset body.
2. Derived-value recomputation counts as a mutation, so it bumps `version` once per request; GET reads (e.g. member reputation decay, `/analytics`) re-derive for display without bumping.
3. No format validation on `Department.code` or `Dataset.slug` (uniqueness only) — the PRD specifies shape prose but no error id.
4. No dataset-state gate on creating metadata records, privacy assessments, quality issues or showcases (gates apply on their transitions instead).
5. `POST /pipeline-runs` does not require the pipeline to be `ARMED`; the window/credit gates live on `arm` and the run transitions.
6. `link-correction` clears `correction_breached`.
7. Conditionally-required body fields are validated at precedence 4.
8. `usage-report` allowed from `SCREENING` onward; re-scores under the variant the *current* `publication_status` selects (per §3.8), while `votes`/`fulfill` re-score under the stored `priority_score_variant`.
9. Decimals serialise as JSON floats; `api_request_timestamp` uses wall clock, `created_at`/`updated_at` use the logical clock.
10. `POST /departments/{id}/credit-grants` returns 200 (mutation of an existing row, not a new resource).
11. List filters implement the scaffold's per-collection filters as a strict superset of PRD §2.3; unknown enum values → `ERR_INVALID_REQUEST`, booleans accept `true/false/1/0`.
12. `POST /quality-issues/{id}/decide`: the `SUSPENDED`-posture gate applies to `ACCEPT` only, following §3.7's specific prose.
13. Metadata `ACCEPT` gates ordered by §2.7 precedence (18 licence-retired → 26 completeness ≥ 85.00 → 27 attribution) rather than §3.2's prose order.
14. `fulfill` against a dataset outside `{SCREENING, READY, PUBLISHED}` → `ERR_INVALID_STATE_TRANSITION` (both candidate errors are 409).
15. `retract` re-derives currency only, not the department (the PRD names only the currency hop there).
16. `PATCH /metadata-records` legal from `DRAFT` and `RETURNED` (`RETURNED → DRAFT` clears `returned_reason`); a supplied unknown `license_id` → `ERR_LICENSE_NOT_FOUND`.
17. Privacy `submit`/`reopen` dataset-state guards surface as `ERR_INVALID_STATE_TRANSITION`.
18. Server runs single-threaded so the shared in-memory store needs no locking.
19. Pipeline suspension only re-derives currency / emits staleness when the dataset is in `{PUBLISHED, UNDER_REMEDIATION}`.

## Step 7: Run tests and iterate — 2026-09-02T10:22:41.000Z

Clean exit after one iteration.

## Summary

**Iterations run: 1** (single 8-round parallel sweep; no fixes were needed).

I deleted the 8 stale `results.*.json` from the prior attempt, cleared `workspace/sweeplogs/`, and ran a fresh 8-round parallel stability sweep under `setsid nohup` exactly as specified (`--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`, no `--api-url`). All 8 rounds ran to completion (~430 s wall each, joined by `wait`, no reaping — zero `Terminated` in any round log, all 8 emitted their final `Results:` line).

**Result: all 8 rounds green — 120/120 passed, 0 failed, 0 errors, 0 skipped in every round.** Verified two ways: the runner's own summary line in each `round_$i.log`, and a per-test scan of all 8 `results.$i.json` (960 test outcomes, zero non-passing). The union of failing tests across rounds is empty, so no flakiness surfaced either.

- **Tests deleted: none.** No test failed any round, so no PRD-coverage / unique-derivability adjudication was triggered.
- **Fixes applied to `test_helpers/`: none.**
- **Fixes applied to `implementation/`: none.**

Notes for the caller:
- The prior attempt's reported 94–109/120 does not reproduce. I re-derived from scratch rather than trusting it; on the current on-disk artifact the suite is fully green and stable across 8 concurrent rounds. The prior attempt evidently landed fixes in `test_suite/`, `test_helpers/`, and/or `implementation/` before it stopped — I cannot attribute those, and I added nothing on top.
- While waiting on the sweep I read the full PRD (`workspace/PRD.md`), the whole implementation (`app.py`, `core.py`, `calc.py`, `services.py`, `common.py`, `routes/{registry,datasets,artifacts,pipelines,community,ops}.py`) and the test-helper layer (`fixtures.py`, `factories.py`, `test_users.py`, `constants.py`). I found no PRD-contract divergence worth pre-emptively changing: the pinned rounding orders (§2.5 metadata per-component rounding, single-round reidentification before the cap, settlement tier keyed on the pre-discount subtotal), the half-open runner-exclusivity span vs. closed departmental-capacity span, the credit-conservation waterfall, and the `STALE` pipeline floor are all implemented as the PRD states.
- Storage is in-memory only (`core.Store`, reset on every boot) with no seeded entity data, so the per-test-server isolation wipes state cleanly — consistent with the benchmark's no-data rule.
- Leftover helper scripts from the prior attempt (`workspace/sweep.sh`, `auto_sweep.sh`, `wait_and_sweep.sh`, `classify.py`) are untouched; I ran the sweep inline instead. The 8 fresh `results.*.json` are in `workspace/implementation/` as the specified command directs.

### Orchestrator adjudication of the Step 8 skip condition

The Step 7 subagent could not attribute the prior attempt's fixes, so the orchestrator resolved it from artifact mtimes. Every file under `test_suite/`, `test_helpers/` and `workspace/implementation/` has an mtime inside the Step 5/6 generation windows (test gen 06:16:13–07:15:19, impl gen 07:23:47–07:41:48), both of which close before the worklog's Step 5/6 completion stamp of 07:47:31. **No artifact was modified after 07:41:48** — i.e. the prior attempt's sweep (results written 08:55–08:57) ran against exactly the same bytes that now pass 120/120 × 8, and it applied zero fixes before dying.

Therefore the prior attempt's 94–109/120 was not a real failure state: it was the load-induced / reaped-sweep artifact the resume protocol explicitly warns about (this host runs many of these pipelines concurrently). The genuine Step 7 result is a first-sweep clean exit on pure Step 5/6 output: 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes.

**Decision: Step 8 is SKIPPED** per its stated skip condition (zero iterations beyond the baseline). There is no `<step_7_diff>` to hand it — with an empty diff, Step 8's hard scope rule ("every PRD edit must trace to a specific fix listed in `<step_7_diff>`") makes it a no-op by construction, and spawning it could only produce out-of-scope edits. `PRD_FINALIZED.md` will be absent, so Step 9 takes `PRD.md` as its source. Step 9's global PRD-vs-implementation scan is strictly broader than Step 8's targeted patch, so nothing is lost by the skip.

## Step 8: Finalize PRD — 2026-09-02T10:23:00.000Z

SKIPPED. Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — the skip condition stated in the skill. Rationale and the mtime evidence that established the prior attempt applied no fixes are recorded at the end of the Step 7 entry above. `workspace/PRD_FINALIZED.md` is therefore absent by design, and Step 9 took `workspace/PRD.md` as its source.

## Step 9: Complete PRD — 2026-09-02T13:48:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Exit summary

| | source `workspace/PRD.md` | `workspace/PRD_COMPLETED.md` |
|---|---|---|
| lines | 494 | 494 (0 added, 0 removed, 42 modified in place) |
| chars | 102,336 | 115,329 (**+12,993**) |
| sections | 27 headings | 27 headings (none added) |

**Ambiguity-pins (PRD was silent): 27. Mismatch-revisions (PRD contradicted impl): 15. Total: 42.**

All paths below are relative to `workspace/implementation/`.

- §2 preamble — insert — ambiguity — pinned the unauthenticated `GET /health` probe mounted outside `/open-data`, answering a bare `{"status":"ok"}` rather than the envelope, and trailing-slash tolerance — `app.py:22,53-55`
- §2.1 — insert — ambiguity — pinned that an `X-User-ID` sent with `Anonymous` is ignored, and that a present-but-blank `X-User-ID` counts as missing — `core.py:260-267`
- §2.3 — insert — ambiguity — pinned that `limit`/`offset` must be plain decimal integers (empty, non-numeric, fractional, signed or zero-padded refused; whitespace tolerated) and that an empty value counts as supplied — `core.py:398-422`
- §2.3 — insert — ambiguity — pinned the list tie-break as process creation sequence and the exact `has_more` formula — `core.py:203-210,229`
- §2.3 — revise — mismatch — PRD claimed only two collections define filters and "no other collection endpoint defines a named filter"; enumerated all twelve filtered collections plus enum/boolean/identifier filter semantics and that undefined query params are ignored — `registry.py:81-93,193-211,251-263`, `datasets.py:164-196`, `artifacts.py:95-112,288-305`, `pipelines.py:118-139,274-289,439-463`, `community.py:98-119,275-290`
- §2.4 — insert — ambiguity — pinned that a row created by the request stays at `version` 1 no matter how often the request re-derives it — `core.py:187-201`
- §2.6 — revise — mismatch — PRD said other endpoints "do not accept" `expected_dataset_version`; impl silently ignores it — `pipelines.py:79,420`
- §2.7 item 4 — insert — ambiguity — completed the numeric-bound list (`initial_row_count`, `epoch_index`, `api_call_count`, `download_count`; `expected_dataset_version` unbounded) and pinned non-object-body rejection, blank-string rejection, discriminator dependents, and that `code`/`slug`/`email` formats are never enforced — `core.py:276-397`
- §2.7 item 5 — insert — ambiguity — pinned that `PATCH /metadata-records/{id}` resolves a supplied `license_id` *after* the scope check — `artifacts.py:119-131`
- §2.7 item 6 — revise — mismatch — PRD implied scope on every coordinator write; impl compares nothing on role-shared endpoints except `decommission` (and only for a `DataCoordinator` caller) — `pipelines.py:183-236,296-410,470-497`, `community.py:234-247`, `registry.py:102-105`
- §2.7 item 33 — revise — mismatch — posture gate on issue-decide applies only when `decision` is `ACCEPT` — `community.py:147-198`
- §2.9 — revise — mismatch — same ACCEPT-only qualification on the "five operations" prose — `community.py:147-198`
- §3.1 — insert — ambiguity — pinned that department `code` shape is unenforced, `credit_units` may be fractional, `memo` is validated but not stored, and the scorecard is a pure read with no ownership comparison — `registry.py:49-78,102-145`
- §3.1 — insert — ambiguity — pinned that `slug` shape is unenforced, declared scores are stored verbatim, and `embargo_until_utc` / `aggregation_geography` are optional defaulting to null — `datasets.py:81-138`
- §3.2 — insert — ambiguity — pinned that licence retirement is idempotent — `registry.py:220-226`
- §3.2 — revise — mismatch — metadata create imposes no condition on the dataset's `publication_status`; submit is the step that demands `SCREENING` — `artifacts.py:55-94`
- §3.2 — revise — mismatch — PATCH is legal from `DRAFT` **or** `RETURNED` (not `DRAFT` alone), omitted fields keep stored values, and `version` increments even for an empty body — `artifacts.py:119-155`
- §3.2 — revise — mismatch — the ACCEPT decision evaluates `completeness_score` **before** attribution readiness (PRD listed them reversed) — `artifacts.py:172-211`
- §3.3 — revise — mismatch — assessment create imposes no dataset-state condition, and it sets `k_anonymity_k`, leaves `clearance_risk_score` null and immediately runs the screening variant so all derived fields are populated on creation — `artifacts.py:251-287`
- §3.3 — revise — mismatch — on submit the `SCREENING` dataset check runs *first* (`ERR_INVALID_STATE_TRANSITION`), before `ERR_VERIFIED_CELL_SIZE_MISSING` — `artifacts.py:337-355`
- §3.3 — insert — ambiguity — pinned that a missing `block_reason` is `ERR_INVALID_REQUEST` and that BLOCK leaves `clearance_risk_score` in place — `artifacts.py:357-388`
- §3.3 — insert — ambiguity — pinned `ERR_INVALID_STATE_TRANSITION` for reopen outside `SCREENING` — `artifacts.py:390-404`
- §3.5 — revise — mismatch — pipeline configure does not examine the dataset's `publication_status`; also pinned that all superseded pipelines are decommissioned with `superseded_pipeline_id` naming the newest, and that the window-geometry check precedes superseding — `pipelines.py:70-117`
- §3.5 — insert — ambiguity — pinned `suspend_reason` default `ADMIN_REQUEST` with the three accepted overrides, no scope check, `armed_window_count` floored at 0, `last_staleness_alert_at` stamping, and that currency/alert/department effects apply only for `PUBLISHED`/`UNDER_REMEDIATION` datasets — `pipelines.py:184-194`, `services.py` (`suspend_pipeline`)
- §3.5 — revise — mismatch — decommission scope applies from any origin and only to `DataCoordinator` callers; added the `PIPELINE_DECOMMISSIONED` run skip and pinned that department counters are *not* re-derived — `pipelines.py:222-236`, `services.py` (`decommission_pipeline`)
- §3.6 — insert — ambiguity — pinned that run scheduling does not examine the pipeline's `status`, and listed the eight settlement fields initialised to 0.00 — `pipelines.py:238-273`
- §3.6 — insert — ambiguity — pinned that report-success resets `alert_dispatched` to false before settling — `pipelines.py:328-354`
- §3.6 — revise — mismatch — auto-suspend fires at a streak of 3 **or more** and only while the pipeline is still `ARMED` — `pipelines.py:356-383`
- §3.6 — insert — ambiguity — pinned that `correction_issue_id` need only resolve (dataset and `change_type` uncross-checked), that department counters are re-derived, and that the 201 body is the version, not the dataset — `pipelines.py:412-438`
- §3.6 — insert — ambiguity — pinned that retraction applies no ownership comparison and does not re-derive the department — `pipelines.py:471-497`
- §3.7 — insert — ambiguity — pinned that the individual member read re-derives in place but leaves `updated_at`/`version` untouched — `registry.py:320-325`
- §3.7 — revise — mismatch — issue filing does not examine the dataset's `publication_status`, and the throttle reads the member's stored `status` without re-deriving reputation — `community.py:61-97`
- §3.7 — insert — ambiguity — pinned `ERR_DATASET_NOT_PUBLISHED` for triage outside `PUBLISHED`/`UNDER_REMEDIATION`, checked after transition legality — `community.py:127-146`
- §3.7 — revise — mismatch — split link-correction failures into `ERR_INVALID_STATE_TRANSITION` (wrong dataset / wrong `change_type`) vs `ERR_VERSION_NOT_LIVE`, and corrected the claim that the dataset's `version` always increments — it moves only when remediation is actually lifted — `community.py:200-233`
- §3.7 — revise — mismatch — the vote's `weight` snapshots the **freshly re-derived** `vote_weight`, not the value at the moment of casting; also pinned dup → throttle → recompute order and the stored-`status` throttle read — `community.py:298-321`
- §3.8 — insert — ambiguity — pinned that `ERR_INSUFFICIENT_DEMAND` is checked after transition legality, and that an omitted review note leaves the stored one untouched — `community.py:323-341`
- §3.8 — insert — ambiguity — pinned `ERR_INVALID_STATE_TRANSITION` for a fulfilling dataset outside `SCREENING`/`READY`/`PUBLISHED`, checked after the request's own transition — `community.py:363-377`
- §3.8 — insert/revise — ambiguity — pinned that showcase submit ignores dataset state and returns a 201 carrying the dataset; that `decision` is `APPROVE`/`REJECT` with `APPROVED`/`REJECTED` as synonyms and anything else `ERR_INVALID_REQUEST`; and that only a `SUBMITTED` entry is moderatable — `datasets.py:30-35,403-427,430-454`
- §3.8 — revise — mismatch — usage reporting is refused for `INVENTORIED` **and** `RETIRED` (PRD said only "earlier" states), and the state test runs after the duplicate-epoch test — `datasets.py:356-382`
- §3.8 — insert — ambiguity — pinned that the analytics read computes every figure live from `usage_epochs`, persists nothing (no `updated_at`/`version` movement, so it may disagree with a dataset read), reports the stored variant's score/tier, and defines `open_issue_count` — `datasets.py:205-241`
- §3.9 — insert — ambiguity — pinned each sweep counter's exact denominator, notably that `issues_triage_breached`/`issues_correction_breached` count only newly latched flags (zero on a repeat sweep), that `departments_recomputed` covers all departments, and that participants are `touch`ed even on no-op — `ops.py:12-85`
- §5 — insert — ambiguity — pinned the three off-catalogue transport errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500), all in the standard envelope — `app.py:36-51`

Method held: only `PRD_COMPLETED.md` was edited (created by `cp PRD.md PRD_COMPLETED.md`), every change is an in-paragraph insert or revision, no new sections or paragraphs were added, and `SCAFFOLD*.yaml` / `worklog.md` were never opened.
